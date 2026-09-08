import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../orders/order_models.dart';
import 'transport_models.dart';
import 'transport_repository.dart';

/// Окно «Доставлена» для заявки на перевозку (ТЗ 09.2026, п. 3):
/// «в окне все те же окна с маршрутом и тд с датой. Все окна должны быть
/// заполнены, и можно изменить. Коммент только пустое поле».
///
/// Поэтому маршрут и дата предзаполнены значениями заявки, доступны к правке
/// и обязательны; комментарий — единственное необязательное поле.
/// Возвращает null, если водитель закрыл окно, не отправив.
Future<Order?> showTransportDeliveryDialog(
  BuildContext context, {
  required String orderId,
  required String orderNumber,
}) async {
  TransportDetail detail;
  try {
    detail = await TransportRepository.instance.getDetail(orderId);
  } on Object catch (e) {
    if (!context.mounted) return null;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Не удалось загрузить перевозку: ${apiErrorMessage(e)}')),
    );
    return null;
  }
  // Справочники нужны, чтобы показать названия точек. Водителю бэкенд их не
  // отдаёт (403) — тогда останутся сами точки заявки, без выбора новых.
  final dir = await TransportRepository.instance.loadDirectory();
  if (!context.mounted) return null;

  return showDialog<Order>(
    context: context,
    barrierDismissible: false,
    builder: (_) => _TransportDeliveryDialog(
      orderId: orderId,
      orderNumber: orderNumber,
      detail: detail,
      bases: dir.bases,
      objects: dir.objects,
    ),
  );
}

class _TransportDeliveryDialog extends StatefulWidget {
  const _TransportDeliveryDialog({
    required this.orderId,
    required this.orderNumber,
    required this.detail,
    required this.bases,
    required this.objects,
  });

  final String orderId;
  final String orderNumber;
  final TransportDetail detail;
  final List<TransportBase> bases;
  final List<TransportClientObject> objects;

  @override
  State<_TransportDeliveryDialog> createState() => _TransportDeliveryDialogState();
}

class _TransportDeliveryDialogState extends State<_TransportDeliveryDialog> {
  late RoutePoint? _from = widget.detail.routeFrom;
  late RoutePoint? _to = widget.detail.routeTo;
  late final List<RoutePoint?> _waypoints =
      List<RoutePoint?>.from(widget.detail.waypoints);
  late final TextEditingController _date =
      TextEditingController(text: widget.detail.desiredDateText ?? '');
  final TextEditingController _comment = TextEditingController();

  bool _sending = false;
  String? _error;

  @override
  void dispose() {
    _date.dispose();
    _comment.dispose();
    super.dispose();
  }

  /// Подпись точки: сначала справочник, иначе сохранённый текст.
  String _label(RoutePoint? p) {
    if (p == null) return '—';
    if (p.kind == RoutePointKind.base) return p.text ?? 'База';
    if (p.kind == RoutePointKind.oilDepot) {
      for (final b in widget.bases) {
        if (b.id == p.id) return b.name;
      }
    } else {
      for (final o in widget.objects) {
        if (o.id == p.id) return o.name;
      }
    }
    return p.text ?? 'Точка маршрута';
  }

  /// Варианты точек по типу перевозки — те же правила, что в вебе.
  /// Текущее значение добавляем всегда: справочник водителю недоступен,
  /// и без этого предзаполненная точка выпала бы из списка.
  List<RoutePoint> _options(String slot, RoutePoint? current) {
    final out = <RoutePoint>[];
    void addBases() {
      for (final b in widget.bases) {
        out.add(b.point);
      }
    }

    void addObjects() {
      for (final o in widget.objects) {
        out.add(o.point);
      }
    }

    if (widget.detail.isToBase) {
      if (slot == 'from') {
        addBases();
      } else {
        out.add(const RoutePoint(kind: RoutePointKind.base, text: 'База'));
      }
    } else {
      if (slot == 'from') {
        addBases();
        out.add(const RoutePoint(kind: RoutePointKind.base, text: 'База'));
      }
      addObjects();
    }
    if (current != null && !out.contains(current)) out.insert(0, current);
    return out;
  }

  Widget _pointField(String label, String slot, RoutePoint? value,
      ValueChanged<RoutePoint?> onChanged) {
    final options = _options(slot, value);
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: DropdownButtonFormField<String>(
        initialValue: value?.key,
        isExpanded: true,
        decoration: InputDecoration(
          labelText: label,
          border: const OutlineInputBorder(),
        ),
        items: [
          for (final o in options)
            DropdownMenuItem(value: o.key, child: Text(_label(o))),
        ],
        onChanged: _sending
            ? null
            : (key) {
                for (final o in options) {
                  if (o.key == key) {
                    onChanged(o);
                    break;
                  }
                }
                setState(() {});
              },
      ),
    );
  }

  Future<void> _submit() async {
    // ТЗ: все окна должны быть заполнены; исключение — комментарий.
    if (_from == null || _to == null) {
      setState(() => _error = 'Укажите маршрут: откуда и куда');
      return;
    }
    for (var i = 0; i < _waypoints.length; i++) {
      if (_waypoints[i] == null) {
        setState(() => _error = 'Заполните промежуточную точку ${i + 1}');
        return;
      }
    }
    final date = _date.text.trim();
    if (date.isEmpty) {
      setState(() => _error = 'Укажите дату');
      return;
    }

    setState(() {
      _sending = true;
      _error = null;
    });
    try {
      final order = await TransportRepository.instance.deliver(
        widget.orderId,
        routeFrom: _from!,
        routeTo: _to!,
        waypoints: _waypoints.whereType<RoutePoint>().toList(),
        desiredDateText: date,
        comment: _comment.text.trim().isEmpty ? null : _comment.text.trim(),
      );
      if (mounted) Navigator.of(context).pop(order);
    } on Object catch (e) {
      if (mounted) {
        setState(() {
          _sending = false;
          _error = apiErrorMessage(e);
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text('Перевозка ${widget.orderNumber}'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Text(
                TransportType.label(widget.detail.transportType),
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
            _pointField('Откуда', 'from', _from, (v) => _from = v),
            for (var i = 0; i < _waypoints.length; i++)
              _pointField('Промежуточная точка ${i + 1}', 'waypoint',
                  _waypoints[i], (v) => _waypoints[i] = v),
            _pointField('Куда', 'to', _to, (v) => _to = v),
            TextField(
              controller: _date,
              enabled: !_sending,
              decoration: const InputDecoration(
                labelText: 'Дата *',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _comment,
              enabled: !_sending,
              maxLines: 2,
              decoration: const InputDecoration(
                labelText: 'Комментарий (необязательно)',
                border: OutlineInputBorder(),
              ),
            ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Text(
                  _error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _sending ? null : () => Navigator.of(context).pop(),
          child: const Text('Отмена'),
        ),
        FilledButton(
          onPressed: _sending ? null : _submit,
          child: _sending
              ? const SizedBox(
                  width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
              : const Text('Доставлена'),
        ),
      ],
    );
  }
}
