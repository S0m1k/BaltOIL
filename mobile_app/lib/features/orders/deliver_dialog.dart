import 'package:flutter/material.dart';

import 'order_models.dart';

/// Результат окна «Отметить доставку» (как promptDeliver на вебе).
class DeliverResult {
  DeliverResult({
    required this.volume,
    this.comment,
    this.tankId,
    this.counterAfter,
    this.payAmount,
    this.payMethod,
  });

  final double volume;
  final String? comment;
  final String? tankId;
  final int? counterAfter;
  final double? payAmount; // null — оплату не фиксируем
  final String? payMethod;
}

const _methodLabels = {
  'cash': 'Наличные',
  'card': 'Карта',
  'bank_transfer': 'Банковский перевод',
};

double? _parseNum(String s) => double.tryParse(s.trim().replaceAll(',', '.'));

String _money(double v) => v.toStringAsFixed(2).replaceAll('.', ',');

Future<DeliverResult?> showDeliverDialog(
  BuildContext context, {
  required Order order,
  required List<Tank> tanks,
}) =>
    showDialog<DeliverResult>(
      context: context,
      barrierDismissible: false,
      builder: (_) => _DeliverDialog(order: order, tanks: tanks),
    );

class _DeliverDialog extends StatefulWidget {
  const _DeliverDialog({required this.order, required this.tanks});

  final Order order;
  final List<Tank> tanks;

  @override
  State<_DeliverDialog> createState() => _DeliverDialogState();
}

class _DeliverDialogState extends State<_DeliverDialog> {
  late final TextEditingController _volume;
  final _comment = TextEditingController();
  final _counter = TextEditingController();
  final _amount = TextEditingController();
  late final List<Tank> _tanks;
  Tank? _tank;
  bool _paid = true;
  String _method = 'cash';
  String? _error;

  Order get _order => widget.order;
  bool get _showPayment => _order.isIndividual;
  bool get _alreadyPaid => _order.paymentStatus == 'paid';

  /// Цена за литр из суммы заявки — для живой формулы «цена × литры + доставка».
  double get _perLiter {
    final total = _order.finalAmount ?? _order.expectedAmount ?? 0;
    if (total <= 0 || _order.volumeRequested <= 0) return 0;
    return (total - (_order.deliveryCost ?? 0)) / _order.volumeRequested;
  }

  double get _delivery => _order.deliveryCost ?? 0;

  @override
  void initState() {
    super.initState();
    _volume = TextEditingController(
        text: _order.volumeRequested.toStringAsFixed(0));
    // Сначала ёмкости с топливом заявки, затем прочие.
    _tanks = [...widget.tanks]..sort((a, b) =>
        (b.fuelType == _order.fuelType ? 1 : 0) -
        (a.fuelType == _order.fuelType ? 1 : 0));
    if (_tanks.isNotEmpty) _tank = _tanks.first;
    _recalc();
    _volume.addListener(() {
      _recalc();
      setState(() {});
    });
  }

  @override
  void dispose() {
    _volume.dispose();
    _comment.dispose();
    _counter.dispose();
    _amount.dispose();
    super.dispose();
  }

  // Сумма к оплате пересчитывается по фактически слитым литрам.
  void _recalc() {
    final vol = _parseNum(_volume.text) ?? 0;
    if (_perLiter > 0 && vol > 0) {
      _amount.text = (_perLiter * vol + _delivery).toStringAsFixed(2);
    } else if (_amount.text.isEmpty) {
      final total = _order.finalAmount ?? _order.expectedAmount ?? 0;
      if (total > 0) _amount.text = total.toStringAsFixed(2);
    }
  }

  String? get _formula {
    final vol = _parseNum(_volume.text) ?? 0;
    if (_perLiter <= 0 || vol <= 0) return null;
    final total = _perLiter * vol + _delivery;
    return '${_money(_perLiter)} ₽/л × ${vol.toStringAsFixed(0)} л'
        '${_delivery > 0 ? ' + ${_delivery.toStringAsFixed(0)} ₽ доставка' : ''}'
        ' = ${_money(total)} ₽';
  }

  String? get _counterHint {
    final t = _tank;
    if (t == null) return null;
    final base = 'Текущее показание: ${t.counter.toString().padLeft(6, '0')}';
    final after = int.tryParse(_counter.text.trim());
    if (after == null || after < 0 || after > 999999) return base;
    // Переполнение шестизначного счётчика: 999999 → 0.
    final litres =
        after >= t.counter ? after - t.counter : 1000000 - t.counter + after;
    final vol = _parseNum(_volume.text) ?? 0;
    final mismatch = vol > 0 && (litres - vol).abs() > 0.5
        ? ' ⚠ не сходится с объёмом (${vol.toStringAsFixed(0)} л)'
        : '';
    return '$base · по счётчику: $litres л$mismatch';
  }

  void _submit() {
    final vol = _parseNum(_volume.text);
    if (vol == null || vol <= 0) {
      setState(() => _error = 'Укажите отгруженный объём');
      return;
    }
    int? counterAfter;
    if (_tank != null) {
      counterAfter = int.tryParse(_counter.text.trim());
      if (counterAfter == null || counterAfter < 0 || counterAfter > 999999) {
        setState(() => _error = 'Введите показание счётчика (число до 6 цифр)');
        return;
      }
    }
    double? payAmount;
    if (_showPayment && !_alreadyPaid && _paid) {
      payAmount = _parseNum(_amount.text);
      if (payAmount == null || payAmount <= 0) {
        setState(() => _error = 'Укажите сумму оплаты');
        return;
      }
    }
    Navigator.of(context).pop(DeliverResult(
      volume: vol,
      comment: _comment.text.trim().isEmpty ? null : _comment.text.trim(),
      tankId: _tank?.id,
      counterAfter: counterAfter,
      payAmount: payAmount,
      payMethod: payAmount == null ? null : _method,
    ));
  }

  @override
  Widget build(BuildContext context) {
    final muted = Theme.of(context).hintColor;
    final small = TextStyle(fontSize: 12, color: muted);
    final formula = _formula;
    final hint = _counterHint;

    return AlertDialog(
      title: const Text('Отметить доставку'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              controller: _volume,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                labelText: 'Отгружено, литров *',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 4),
            Text(
                'Сумма заявки будет пересчитана по фактическому объёму. '
                'Номер ТТН присваивается автоматически.',
                style: small),
            if (_tanks.isNotEmpty) ...[
              const SizedBox(height: 12),
              DropdownButtonFormField<Tank>(
                initialValue: _tank,
                isExpanded: true,
                items: [
                  for (final t in _tanks)
                    DropdownMenuItem(
                      value: t,
                      child: Text(
                        '${t.name} · ${t.fuelLabel}'
                        '${t.fuelType != _order.fuelType ? ' ⚠ другое топливо' : ''}'
                        ' · ${t.currentVolume.toStringAsFixed(0)} л',
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                ],
                onChanged: (t) => setState(() => _tank = t),
                decoration: const InputDecoration(
                  labelText: 'Из какой ёмкости *',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _counter,
                keyboardType: TextInputType.number,
                maxLength: 6,
                onChanged: (_) => setState(() {}),
                decoration: InputDecoration(
                  labelText: 'Счётчик после отгрузки (6 цифр) *',
                  counterText: '',
                  hintText: _tank?.counter.toString().padLeft(6, '0'),
                  border: const OutlineInputBorder(),
                ),
              ),
              if (hint != null) Text(hint, style: small),
            ],
            const SizedBox(height: 12),
            TextField(
              controller: _comment,
              maxLines: 2,
              decoration: const InputDecoration(
                labelText: 'Комментарий (необязательно)',
                hintText: 'Попадёт в отчёт: недолив, замечания по адресу',
                border: OutlineInputBorder(),
              ),
            ),
            if (_showPayment && _alreadyPaid) ...[
              const SizedBox(height: 12),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: const Color(0xFF0D9488).withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Text('✓ Топливо оплачено',
                    style: TextStyle(
                        color: Color(0xFF0D9488), fontWeight: FontWeight.w600)),
              ),
            ] else if (_showPayment) ...[
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                value: _paid,
                onChanged: (v) => setState(() => _paid = v ?? false),
                title: const Text('Оплата получена'),
              ),
              if (_paid) ...[
                if (formula != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: Text(formula, style: small),
                  ),
                TextField(
                  controller: _amount,
                  keyboardType:
                      const TextInputType.numberWithOptions(decimal: true),
                  decoration: const InputDecoration(
                    labelText: 'Сумма, ₽ *',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue: _method,
                  items: [
                    for (final e in _methodLabels.entries)
                      DropdownMenuItem(value: e.key, child: Text(e.value)),
                  ],
                  onChanged: (v) => setState(() => _method = v ?? 'cash'),
                  decoration: const InputDecoration(
                    labelText: 'Метод оплаты',
                    border: OutlineInputBorder(),
                  ),
                ),
              ],
            ],
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Text(_error!,
                    style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Отмена'),
        ),
        FilledButton(onPressed: _submit, child: const Text('Подтвердить')),
      ],
    );
  }
}
