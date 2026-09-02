import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../inventory/inventory_repository.dart';
import 'order_models.dart';
import 'orders_repository.dart';

/// Подписи метода оплаты — как в селекте веба (promptDriverRecordPayment).
const _kMethodLabels = <String, String>{
  'cash': 'Наличные',
  'card': 'Карта',
  'bank_transfer': 'Банковский перевод',
};

/// Результат окна доставки/оплаты.
///
/// [delivered] — заявка после перевода в delivered (null в режиме
/// «только оплата»: статус не менялся).
class DeliveryResult {
  const DeliveryResult({
    this.delivered,
    this.paymentRecorded = false,
    this.warning,
  });

  final Order? delivered;

  /// Оплата успешно отправлена (или поставлена в офлайн-очередь).
  final bool paymentRecorded;

  /// Некритичная проблема (например, ёмкость не списана) — показать снекбаром.
  final String? warning;
}

/// CRM-38: одно окно «Доставка» для физлица — литры, ёмкость/счётчик,
/// сумма и способ оплаты. Диалог сам отправляет данные:
/// 1) transition → delivered, 2) списание из ёмкости (некритично),
/// 3) record_payment. Если упал шаг 3 — окно остаётся с кнопкой
/// «Повторить оплату», статус уже переведён и повторно не отправляется.
///
/// Для юрлиц ([collectPayment] = false) — прежнее окно без денег.
/// Возвращает null, если водитель отменил окно до отправки.
Future<DeliveryResult?> showDeliveryDialog(
  BuildContext context, {
  required String orderId,
  required String orderNumber,
  required double requestedVolume,
  required String fuelType,
  bool collectPayment = false,
  double? expectedAmount,
}) async {
  List<Tank> tanks;
  try {
    tanks = (await InventoryRepository.instance.listTanks())
        .where((t) => t.isActive)
        .toList();
  } on Object {
    tanks = const []; // блок ёмкости останется скрыт
  }
  tanks.sort((a, b) => (b.fuelType == fuelType ? 1 : 0)
      .compareTo(a.fuelType == fuelType ? 1 : 0));
  if (!context.mounted) return null;

  return showDialog<DeliveryResult>(
    context: context,
    barrierDismissible: false,
    builder: (_) => _DeliveryDialog(
      orderId: orderId,
      orderNumber: orderNumber,
      requestedVolume: requestedVolume,
      fuelType: fuelType,
      tanks: tanks,
      collectPayment: collectPayment,
      expectedAmount: expectedAmount,
    ),
  );
}

/// Оплата по уже доставленной заявке физлица (Д5: деньги можно внести позже).
/// Тот же виджет в режиме «только оплата» — без литров и ёмкости.
Future<DeliveryResult?> showDriverPaymentDialog(
  BuildContext context, {
  required String orderId,
  required String orderNumber,
  double? expectedAmount,
}) {
  return showDialog<DeliveryResult>(
    context: context,
    barrierDismissible: false,
    builder: (_) => _DeliveryDialog(
      orderId: orderId,
      orderNumber: orderNumber,
      requestedVolume: 0,
      fuelType: '',
      tanks: const [],
      collectPayment: true,
      expectedAmount: expectedAmount,
      paymentOnly: true,
    ),
  );
}

class _DeliveryDialog extends StatefulWidget {
  const _DeliveryDialog({
    required this.orderId,
    required this.orderNumber,
    required this.requestedVolume,
    required this.fuelType,
    required this.tanks,
    required this.collectPayment,
    this.expectedAmount,
    this.paymentOnly = false,
  });

  final String orderId;
  final String orderNumber;
  final double requestedVolume;
  final String fuelType;
  final List<Tank> tanks;
  final bool collectPayment;
  final double? expectedAmount;
  final bool paymentOnly;

  @override
  State<_DeliveryDialog> createState() => _DeliveryDialogState();
}

class _DeliveryDialogState extends State<_DeliveryDialog> {
  late final TextEditingController _volumeCtrl = TextEditingController(
    text: widget.requestedVolume > 0
        ? widget.requestedVolume.toStringAsFixed(0)
        : '',
  );
  final _counterCtrl = TextEditingController();
  final _commentCtrl = TextEditingController();
  late final TextEditingController _amountCtrl = TextEditingController(
    text: (widget.expectedAmount ?? 0) > 0
        ? widget.expectedAmount!.toStringAsFixed(0)
        : '',
  );

  late String? _tankId = widget.tanks.isNotEmpty ? widget.tanks.first.id : null;
  String _method = 'cash';
  String? _error;
  bool _submitting = false;

  /// Заполняется после успешного шага 1 — окно переходит в режим «повторить
  /// оплату»: доставка уже зафиксирована, поля отгрузки заблокированы.
  Order? _delivered;
  String? _warning;

  bool get _deliveryDone => widget.paymentOnly || _delivered != null;

  @override
  void dispose() {
    _volumeCtrl.dispose();
    _counterCtrl.dispose();
    _commentCtrl.dispose();
    _amountCtrl.dispose();
    super.dispose();
  }

  Tank? _tankById(String? id) {
    for (final t in widget.tanks) {
      if (t.id == id) return t;
    }
    return null;
  }

  // Литры по счётчику с переполнением шестизначного счётчика (999999 → 0).
  String _counterHint() {
    final t = _tankById(_tankId);
    if (t == null) return '';
    final base = 'Текущее показание: ${t.counterText}';
    final afterRaw = _counterCtrl.text.trim();
    if (afterRaw.isEmpty) return base;
    final after = int.tryParse(afterRaw);
    if (after == null || after < 0 || after > 999999) return base;
    final litres =
        after >= t.counter ? after - t.counter : 1000000 - t.counter + after;
    final vol =
        double.tryParse(_volumeCtrl.text.trim().replaceAll(',', '.')) ?? 0;
    final mismatch = vol > 0 && (litres - vol).abs() > 0.5
        ? ' ⚠ не сходится с объёмом (${vol.toStringAsFixed(0)} л)'
        : '';
    return '$base · по счётчику: $litres л$mismatch';
  }

  double? _validAmount() {
    final amount = double.tryParse(_amountCtrl.text.trim().replaceAll(',', '.'));
    if (amount == null || amount <= 0) return null;
    return amount;
  }

  Future<void> _submit() async {
    if (_submitting) return;

    double? volume;
    int? counterAfter;
    if (!_deliveryDone) {
      volume = double.tryParse(_volumeCtrl.text.trim().replaceAll(',', '.'));
      if (volume == null || volume <= 0) {
        setState(() => _error = 'Укажите отгруженный объём');
        return;
      }
      if (widget.tanks.isNotEmpty) {
        if (_tankId == null) {
          setState(() => _error = 'Выберите ёмкость');
          return;
        }
        counterAfter = int.tryParse(_counterCtrl.text.trim());
        if (counterAfter == null || counterAfter < 0 || counterAfter > 999999) {
          setState(
              () => _error = 'Введите показание счётчика (число до 6 цифр)');
          return;
        }
      }
    }

    double? amount;
    if (widget.collectPayment) {
      amount = _validAmount();
      if (amount == null) {
        setState(() => _error = 'Укажите полученную сумму');
        return;
      }
    }

    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      // Шаг 1 — перевод в delivered. Повторно не отправляется: при ретрае
      // оплаты _delivered уже заполнен.
      if (!_deliveryDone) {
        final comment = _commentCtrl.text.trim();
        final delivered = await OrdersRepository.instance.markDelivered(
          widget.orderId,
          volumeDelivered: volume,
          comment: comment.isEmpty ? null : comment,
        );
        _delivered = delivered;
        // Шаг 2 — списание из ёмкости. Ошибка не отменяет доставку:
        // расхождение исправит админ корректировкой.
        if (_tankId != null && counterAfter != null) {
          try {
            await InventoryRepository.instance.tankIssue(
              _tankId!,
              counterAfter: counterAfter,
              orderId: widget.orderId,
              orderNumber: widget.orderNumber,
              volumeHint: volume,
            );
          } on Object catch (te) {
            _warning =
                'Доставка отмечена, но ёмкость не списана: ${apiErrorMessage(te)}';
          }
        }
      }
      // Шаг 3 — оплата (только физлица).
      if (amount != null) {
        await OrdersRepository.instance.recordPayment(
          orderId: widget.orderId,
          amount: amount,
          method: _method,
        );
      }
      if (!mounted) return;
      Navigator.of(context).pop(DeliveryResult(
        delivered: _delivered,
        paymentRecorded: amount != null,
        warning: _warning,
      ));
    } on Object catch (e) {
      if (!mounted) return;
      setState(() {
        _error = _deliveryDone
            ? 'Оплата не записана: ${apiErrorMessage(e)}'
            : apiErrorMessage(e);
      });
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  /// Доставка уже прошла, а оплата — нет: закрыть окно без записи денег
  /// (водитель внесёт их позже кнопкой «Оплата» в списке доставленных).
  void _closeAfterDelivery() {
    Navigator.of(context).pop(DeliveryResult(
      delivered: _delivered,
      warning: _warning,
    ));
  }

  @override
  Widget build(BuildContext context) {
    final deliveredNotPaid = _delivered != null && widget.collectPayment;
    return AlertDialog(
      title: Text(widget.paymentOnly ? 'Зафиксировать оплату' : 'Доставка'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (!widget.paymentOnly) ...[
              TextField(
                controller: _volumeCtrl,
                enabled: !_deliveryDone && !_submitting,
                keyboardType:
                    const TextInputType.numberWithOptions(decimal: true),
                decoration: const InputDecoration(
                  labelText: 'Отгружено, литров *',
                  hintText: 'Фактический объём',
                  helperText: 'Сумма заявки будет пересчитана по '
                      'фактическому объёму. Номер ТТН присваивается '
                      'автоматически.',
                  helperMaxLines: 3,
                ),
                onChanged: (_) => setState(() {}),
              ),
              if (widget.tanks.isNotEmpty) ...[
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue: _tankId,
                  isExpanded: true,
                  items: [
                    for (final t in widget.tanks)
                      DropdownMenuItem(
                        value: t.id,
                        child: Text(
                          '${t.name} · ${t.fuelLabel ?? t.fuelType}'
                          '${t.fuelType != widget.fuelType ? ' ⚠ другое топливо' : ''}'
                          ' · ${t.currentVolume.toStringAsFixed(0)} л',
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(fontSize: 13),
                        ),
                      ),
                  ],
                  onChanged: _deliveryDone || _submitting
                      ? null
                      : (v) => setState(() => _tankId = v),
                  decoration:
                      const InputDecoration(labelText: 'Из какой ёмкости *'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _counterCtrl,
                  enabled: !_deliveryDone && !_submitting,
                  keyboardType: TextInputType.number,
                  maxLength: 6,
                  decoration: InputDecoration(
                    labelText: 'Счётчик после отгрузки (6 цифр) *',
                    hintText: _tankById(_tankId)?.counterText ?? '230523',
                    counterText: '',
                    helperText: _counterHint(),
                    helperMaxLines: 3,
                  ),
                  onChanged: (_) => setState(() {}),
                ),
              ],
            ],
            if (widget.collectPayment) ...[
              const SizedBox(height: 12),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: const Color(0xFFD97706).withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  (widget.expectedAmount ?? 0) > 0
                      ? '⚠ Сумма к получению: '
                          '${widget.expectedAmount!.toStringAsFixed(0)} ₽'
                      : '⚠ Сумма не рассчитана — уточните у менеджера',
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    color: Color(0xFFD97706),
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _amountCtrl,
                enabled: !_submitting,
                keyboardType:
                    const TextInputType.numberWithOptions(decimal: true),
                decoration: const InputDecoration(
                  labelText: 'Получено, ₽ *',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                initialValue: _method,
                items: [
                  for (final e in _kMethodLabels.entries)
                    DropdownMenuItem(value: e.key, child: Text(e.value)),
                ],
                onChanged: _submitting
                    ? null
                    : (v) => setState(() => _method = v ?? 'cash'),
                decoration: const InputDecoration(
                  labelText: 'Способ оплаты *',
                  border: OutlineInputBorder(),
                ),
              ),
            ],
            if (!widget.paymentOnly) ...[
              const SizedBox(height: 12),
              TextField(
                controller: _commentCtrl,
                enabled: !_deliveryDone && !_submitting,
                maxLines: 2,
                decoration: const InputDecoration(
                  labelText: 'Комментарий (необязательно)',
                  hintText: 'Попадёт в отчёт: недолив, замечания '
                      'по адресу и т.п.',
                  alignLabelWithHint: true,
                ),
              ),
            ],
            if (deliveredNotPaid)
              const Padding(
                padding: EdgeInsets.only(top: 10),
                child: Text(
                  'Доставка уже зафиксирована — осталось записать оплату.',
                  style: TextStyle(fontSize: 13),
                ),
              ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 10),
                child: Text(
                  _error!,
                  style: const TextStyle(color: Colors.red, fontSize: 13),
                ),
              ),
          ],
        ),
      ),
      actions: [
        if (deliveredNotPaid)
          TextButton(
            onPressed: _submitting ? null : _closeAfterDelivery,
            child: const Text('Закрыть'),
          )
        else
          TextButton(
            onPressed:
                _submitting ? null : () => Navigator.of(context).pop(),
            child: const Text('Отмена'),
          ),
        FilledButton(
          onPressed: _submitting ? null : _submit,
          child: Text(
            _submitting
                ? 'Отправка…'
                : (deliveredNotPaid ? 'Повторить оплату' : 'ОК'),
          ),
        ),
      ],
    );
  }
}
