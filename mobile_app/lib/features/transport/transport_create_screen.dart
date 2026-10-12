import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../auth/auth_repository.dart';
import '../orders/order_models.dart';
import '../orders/orders_repository.dart';
import 'transport_models.dart';
import 'transport_repository.dart';

/// Создание и правка заявки на перевозку (ТЗ 09.2026), паритет с вебом.
///
/// Форма из двух блоков: первый видит водитель (тип, маршрут, количество,
/// топливо, дата, коммент), второй — только менеджер и админ («куплено» с
/// формулами для доставки на базу либо «оплаты» для услуги клиенту).
///
/// По ТЗ после отправки правятся все поля, поэтому тот же экран открывается
/// на существующей перевозке: [orderId] задан → PATCH вместо POST.
class TransportCreateScreen extends StatefulWidget {
  const TransportCreateScreen({super.key, required this.user, this.orderId});

  final CurrentUser user;

  /// id существующей перевозки — экран работает в режиме правки.
  final String? orderId;

  @override
  State<TransportCreateScreen> createState() => _TransportCreateScreenState();
}

class _TransportCreateScreenState extends State<TransportCreateScreen> {
  final _formKey = GlobalKey<FormState>();

  // Блок 1
  final _kg = TextEditingController();
  final _liters = TextEditingController();
  final _dateText = TextEditingController();
  final _comment = TextEditingController();

  // Блок 2 — «куплено» (доставка на базу)
  final _priceKg = TextEditingController();
  final _priceL = TextEditingController();
  final _density = TextEditingController();
  final _total = TextEditingController();

  // Блок 2 — «оплаты» (услуга доставки клиенту)
  final _deliveryPrice = TextEditingController();
  bool _deliveryPaid = false;

  // Блок 2 — водителю
  final _driverAmount = TextEditingController();
  final _driverPercent =
      TextEditingController(text: '${TransportFormulas.defaultDriverPercent.toInt()}');

  /// До четырёх оплат поставщику: сумма + дата.
  final _supplierAmounts = List.generate(4, (_) => TextEditingController());
  final _supplierDates = List<DateTime?>.filled(4, null);

  String _type = TransportType.toBase;
  String? _clientObjectId;
  RoutePoint? _from;
  RoutePoint? _to;
  final List<RoutePoint?> _waypoints = [];
  String? _fuelCode;

  List<TransportBase> _bases = const [];
  List<TransportClientObject> _objects = const [];
  List<FuelType> _fuelTypes = const [];

  bool _loading = true;
  bool _busy = false;
  String? _error;

  /// Введённое руками значение формулы больше не перетирают — как на вебе.
  bool _touchedLiters = false;
  bool _touchedTotal = false;
  bool _touchedDriver = false;

  bool get _isEdit => widget.orderId != null;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final c in [
      _kg, _liters, _dateText, _comment, _priceKg, _priceL, _density, _total,
      _deliveryPrice, _driverAmount, _driverPercent, ..._supplierAmounts,
    ]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final dir = await TransportRepository.instance.loadDirectory();
      final fuels = await OrdersRepository.instance.fuelTypes();
      if (!mounted) return;
      setState(() {
        _bases = dir.bases;
        _objects = dir.objects;
        _fuelTypes = fuels.where((f) => f.isActive).toList();
      });
      if (_isEdit) await _fillFromExisting();
    } on Object catch (e) {
      if (mounted) setState(() => _error = apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _fillFromExisting() async {
    final d = await TransportRepository.instance.getDetail(widget.orderId!);
    if (!mounted) return;
    setState(() {
      _type = d.transportType;
      _clientObjectId = d.clientObjectId;
      _from = d.routeFrom;
      _to = d.routeTo;
      _waypoints
        ..clear()
        ..addAll(d.waypoints);
      _kg.text = _fmt(d.amountKg);
      _liters.text = _fmt(d.amountL);
      _dateText.text = d.desiredDateText ?? '';
      _priceKg.text = _fmt(d.pricePerKg);
      _priceL.text = _fmt(d.pricePerL);
      _density.text = _fmt(d.density);
      _total.text = _fmt(d.totalAmount);
      _deliveryPrice.text = _fmt(d.deliveryPrice);
      _deliveryPaid = d.deliveryPaid;
      _driverAmount.text = _fmt(d.driverPaymentAmount);
      if (d.driverPaymentPercent != null) {
        _driverPercent.text = _fmt(d.driverPaymentPercent);
      }
      for (var i = 0; i < 4 && i < d.supplierPayments.length; i++) {
        _supplierAmounts[i].text = _fmt(d.supplierPayments[i].amount);
        _supplierDates[i] = DateTime.tryParse(d.supplierPayments[i].date ?? '');
      }
      // Загруженные значения считаем введёнными: пересчёт их не тронет.
      _touchedLiters = d.amountL != null;
      _touchedTotal = d.totalAmount != null;
      _touchedDriver = d.driverPaymentAmount != null;
    });
  }

  static String _fmt(double? v) {
    if (v == null) return '';
    return v == v.roundToDouble() ? v.toInt().toString() : v.toString();
  }

  double? _parse(TextEditingController c) {
    final raw = c.text.trim().replaceAll(',', '.');
    return raw.isEmpty ? null : double.tryParse(raw);
  }

  // ── Точки маршрута ─────────────────────────────────────────────────────────
  // Варианты по ТЗ: на базу — откуда нефтебазы, куда «База»; клиенту —
  // откуда нефтебазы/База/объекты, куда и промежуточные — объекты клиентов.
  List<({RoutePoint point, String label})> _pointOptions(String slot) {
    final out = <({RoutePoint point, String label})>[];
    if (_type == TransportType.toBase) {
      if (slot == 'from') {
        for (final b in _bases) {
          out.add((
            point: RoutePoint(kind: RoutePointKind.oilDepot, id: b.id),
            label: b.name,
          ));
        }
      } else {
        out.add((
          point: const RoutePoint(kind: RoutePointKind.base, text: 'База'),
          label: 'База',
        ));
      }
      return out;
    }
    if (slot == 'from') {
      for (final b in _bases) {
        out.add((
          point: RoutePoint(kind: RoutePointKind.oilDepot, id: b.id),
          label: b.name,
        ));
      }
      out.add((
        point: const RoutePoint(kind: RoutePointKind.base, text: 'База'),
        label: 'База',
      ));
    }
    for (final o in _objects) {
      out.add((
        point: RoutePoint(kind: RoutePointKind.clientObject, id: o.id),
        label: o.name,
      ));
    }
    return out;
  }

  static String _pointKey(RoutePoint? p) =>
      p == null ? '' : '${p.kind}:${p.id ?? ''}';

  Widget _pointField({
    required String label,
    required String slot,
    required RoutePoint? value,
    required ValueChanged<RoutePoint?> onChanged,
    bool enabled = true,
  }) {
    final options = _pointOptions(slot);
    final currentKey = _pointKey(value);
    final hasCurrent = options.any((o) => _pointKey(o.point) == currentKey);
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: DropdownButtonFormField<String>(
        key: ValueKey('$slot-$_type-${options.length}-$currentKey'),
        initialValue: hasCurrent && currentKey.isNotEmpty ? currentKey : null,
        isExpanded: true,
        decoration: InputDecoration(labelText: label),
        items: [
          for (final o in options)
            DropdownMenuItem(
              value: _pointKey(o.point),
              child: Text(o.label, overflow: TextOverflow.ellipsis),
            ),
        ],
        onChanged: enabled
            ? (key) {
                final hit = options.firstWhere((o) => _pointKey(o.point) == key);
                onChanged(hit.point);
              }
            : null,
        validator: (v) => v == null || v.isEmpty ? 'Укажите точку' : null,
      ),
    );
  }

  // ── Формулы блока 2 ────────────────────────────────────────────────────────

  void _recalc() {
    final kg = _parse(_kg);
    final density = _parse(_density);
    final computedL = TransportFormulas.litersFromKg(kg, density);
    if (computedL != null && !_touchedLiters) _liters.text = _fmt(computedL);

    final total = TransportFormulas.purchaseTotal(
      amountKg: kg,
      amountL: _parse(_liters),
      pricePerKg: _parse(_priceKg),
      pricePerL: _parse(_priceL),
    );
    if (total != null && !_touchedTotal) _total.text = _fmt(total);

    final driver = TransportFormulas.driverPayment(
      _parse(_total),
      _parse(_driverPercent),
    );
    if (driver != null && !_touchedDriver) _driverAmount.text = _fmt(driver);
    setState(() {});
  }

  List<SupplierPayment> _collectSupplierPayments() {
    final out = <SupplierPayment>[];
    for (var i = 0; i < 4; i++) {
      final amount = _parse(_supplierAmounts[i]);
      final date = _supplierDates[i];
      if (amount == null && date == null) continue;
      out.add(SupplierPayment(
        amount: amount,
        date: date == null
            ? null
            : '${date.year.toString().padLeft(4, '0')}-'
                '${date.month.toString().padLeft(2, '0')}-'
                '${date.day.toString().padLeft(2, '0')}',
      ));
    }
    return out;
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    if (_type == TransportType.toClient && _clientObjectId == null) {
      setState(() => _error = 'Выберите клиента');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    final body = <String, dynamic>{
      'transport_type': _type,
      'client_object_id':
          _type == TransportType.toClient ? _clientObjectId : null,
      'route_from': _from?.toJson(),
      'route_to': _type == TransportType.toBase
          ? const RoutePoint(kind: RoutePointKind.base, text: 'База').toJson()
          : _to?.toJson(),
      'waypoints': _waypoints.whereType<RoutePoint>().map((w) => w.toJson()).toList(),
      'amount_kg': _parse(_kg),
      'amount_l': _parse(_liters),
      'fuel_type': _fuelCode,
      'desired_date_text': _dateText.text.trim().isEmpty ? null : _dateText.text.trim(),
      'comment': _comment.text.trim().isEmpty ? null : _comment.text.trim(),
      'price_per_kg': _parse(_priceKg),
      'price_per_l': _parse(_priceL),
      'density': _parse(_density),
      'total_amount': _parse(_total),
      'supplier_payments':
          _collectSupplierPayments().map((p) => {'amount': p.amount, 'date': p.date}).toList(),
      'delivery_price': _parse(_deliveryPrice),
      'delivery_paid': _deliveryPaid,
      'driver_payment_amount': _parse(_driverAmount),
      'driver_payment_percent': _parse(_driverPercent),
    };
    try {
      if (_isEdit) {
        await TransportRepository.instance.update(widget.orderId!, body);
      } else {
        await TransportRepository.instance.create(body);
      }
      if (mounted) Navigator.of(context).pop(true);
    } on Object catch (e) {
      if (mounted) setState(() => _error = apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_isEdit ? 'Правка перевозки' : 'Заявка на перевозку'),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : Form(
              key: _formKey,
              child: ListView(
                padding: const EdgeInsets.all(20),
                children: [
                  ..._block1(),
                  const SizedBox(height: 8),
                  ..._block2(),
                  if (_error != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 12),
                      child: Text(_error!,
                          style: TextStyle(
                              color: Theme.of(context).colorScheme.error)),
                    ),
                  const SizedBox(height: 20),
                  FilledButton(
                    onPressed: _busy ? null : _submit,
                    child: Text(_busy
                        ? 'Сохраняем…'
                        : (_isEdit ? 'Сохранить' : 'Создать перевозку')),
                  ),
                ],
              ),
            ),
    );
  }

  List<Widget> _block1() => [
        const Text('Информация о доставке',
            style: TextStyle(fontWeight: FontWeight.w600)),
        const SizedBox(height: 12),
        DropdownButtonFormField<String>(
          initialValue: _type,
          isExpanded: true,
          decoration: const InputDecoration(labelText: 'Тип перевозки'),
          items: const [
            DropdownMenuItem(
                value: TransportType.toBase, child: Text('Доставка на базу')),
            DropdownMenuItem(
                value: TransportType.toClient,
                child: Text('Услуга доставки клиенту')),
          ],
          onChanged: (v) => setState(() {
            _type = v ?? TransportType.toBase;
            // Точки прошлого типа недопустимы для нового — сбрасываем.
            _from = null;
            _to = null;
            _waypoints.clear();
          }),
        ),
        const SizedBox(height: 14),
        if (_type == TransportType.toClient) ...[
          DropdownButtonFormField<String>(
            key: ValueKey('client-${_objects.length}-$_clientObjectId'),
            initialValue: _clientObjectId,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Клиент (объект)'),
            items: [
              for (final o in _objects)
                DropdownMenuItem(value: o.id, child: Text(o.name)),
            ],
            onChanged: (v) => setState(() => _clientObjectId = v),
          ),
          const SizedBox(height: 14),
        ],
        _pointField(
          label: 'Откуда',
          slot: 'from',
          value: _from,
          onChanged: (p) => setState(() => _from = p),
        ),
        for (var i = 0; i < _waypoints.length; i++)
          Row(children: [
            Expanded(
              child: _pointField(
                label: 'Промежуточная точка ${i + 1}',
                slot: 'waypoint',
                value: _waypoints[i],
                onChanged: (p) => setState(() => _waypoints[i] = p),
              ),
            ),
            IconButton(
              tooltip: 'Убрать точку',
              icon: const Icon(Icons.close),
              onPressed: () => setState(() => _waypoints.removeAt(i)),
            ),
          ]),
        _pointField(
          label: 'Куда',
          slot: 'to',
          value: _type == TransportType.toBase
              ? const RoutePoint(kind: RoutePointKind.base, text: 'База')
              : _to,
          onChanged: (p) => setState(() => _to = p),
          enabled: _type != TransportType.toBase,
        ),
        if (_waypoints.length < 3)
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed: () => setState(() => _waypoints.add(null)),
              icon: const Icon(Icons.add, size: 18),
              label: const Text('промежуточная точка'),
            ),
          ),
        const SizedBox(height: 6),
        Row(children: [
          Expanded(
            child: TextFormField(
              controller: _kg,
              decoration: const InputDecoration(labelText: 'Количество, кг'),
              keyboardType: TextInputType.number,
              onChanged: (_) => _recalc(),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: TextFormField(
              controller: _liters,
              decoration: const InputDecoration(labelText: 'Количество, л'),
              keyboardType: TextInputType.number,
              onChanged: (_) {
                _touchedLiters = true;
                _recalc();
              },
            ),
          ),
        ]),
        const SizedBox(height: 14),
        // По ТЗ вид топлива можно не указывать.
        DropdownButtonFormField<String?>(
          key: ValueKey('fuel-${_fuelTypes.length}-$_fuelCode'),
          initialValue: _fuelCode,
          isExpanded: true,
          decoration: const InputDecoration(labelText: 'Вид топлива'),
          items: [
            const DropdownMenuItem<String?>(
                value: null, child: Text('— не указан —')),
            for (final f in _fuelTypes)
              DropdownMenuItem<String?>(value: f.code, child: Text(f.label)),
          ],
          onChanged: (v) => setState(() => _fuelCode = v),
        ),
        const SizedBox(height: 14),
        // Дата — свободный текст без календаря (ТЗ).
        TextFormField(
          controller: _dateText,
          decoration: const InputDecoration(
            labelText: 'Желаемая дата доставки',
            hintText: 'например, до 15 сентября',
          ),
        ),
        const SizedBox(height: 14),
        TextFormField(
          controller: _comment,
          decoration: const InputDecoration(labelText: 'Комментарий'),
          maxLines: 2,
        ),
      ];

  List<Widget> _block2() {
    final isToBase = _type == TransportType.toBase;
    return [
      const Divider(height: 28),
      Text(isToBase ? 'Куплено' : 'Оплаты',
          style: const TextStyle(fontWeight: FontWeight.w600)),
      const SizedBox(height: 4),
      const Text('Видят только менеджер и админ. Все поля по желанию.',
          style: TextStyle(fontSize: 12)),
      const SizedBox(height: 12),
      if (isToBase) ...[
        Row(children: [
          Expanded(
            child: TextFormField(
              controller: _priceKg,
              decoration: const InputDecoration(labelText: 'Цена, ₽/кг'),
              keyboardType: TextInputType.number,
              onChanged: (_) => _recalc(),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: TextFormField(
              controller: _priceL,
              decoration: const InputDecoration(labelText: 'Цена, ₽/л'),
              keyboardType: TextInputType.number,
              onChanged: (_) => _recalc(),
            ),
          ),
        ]),
        const SizedBox(height: 14),
        TextFormField(
          controller: _density,
          decoration: const InputDecoration(
            labelText: 'Плотность',
            helperText: 'кг × плотность = литры',
          ),
          keyboardType: TextInputType.number,
          onChanged: (_) => _recalc(),
        ),
        const SizedBox(height: 14),
        TextFormField(
          controller: _total,
          decoration: const InputDecoration(
            labelText: 'Итого, ₽',
            helperText: 'количество × цена',
          ),
          keyboardType: TextInputType.number,
          onChanged: (_) {
            _touchedTotal = true;
            _recalc();
          },
        ),
        const SizedBox(height: 18),
        const Text('Оплаты поставщику',
            style: TextStyle(fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        for (var i = 0; i < 4; i++) ...[
          Row(children: [
            Expanded(
              child: TextFormField(
                controller: _supplierAmounts[i],
                decoration: InputDecoration(labelText: 'Сумма ${i + 1}, ₽'),
                keyboardType: TextInputType.number,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: InkWell(
                onTap: () async {
                  final picked = await showDatePicker(
                    context: context,
                    initialDate: _supplierDates[i] ?? DateTime.now(),
                    firstDate: DateTime(2020),
                    lastDate: DateTime(2100),
                  );
                  if (picked != null) setState(() => _supplierDates[i] = picked);
                },
                child: InputDecorator(
                  decoration: const InputDecoration(labelText: 'Дата'),
                  child: Text(
                    _supplierDates[i] == null
                        ? '—'
                        : '${_supplierDates[i]!.day.toString().padLeft(2, '0')}.'
                            '${_supplierDates[i]!.month.toString().padLeft(2, '0')}.'
                            '${_supplierDates[i]!.year}',
                  ),
                ),
              ),
            ),
          ]),
          const SizedBox(height: 10),
        ],
      ] else ...[
        TextFormField(
          controller: _deliveryPrice,
          decoration:
              const InputDecoration(labelText: 'Стоимость доставки, ₽'),
          keyboardType: TextInputType.number,
        ),
        const SizedBox(height: 6),
        CheckboxListTile(
          value: _deliveryPaid,
          onChanged: (v) => setState(() => _deliveryPaid = v ?? false),
          title: const Text('Получили оплату'),
          contentPadding: EdgeInsets.zero,
          controlAffinity: ListTileControlAffinity.leading,
        ),
      ],
      const SizedBox(height: 12),
      const Text('Водителю', style: TextStyle(fontWeight: FontWeight.w600)),
      const SizedBox(height: 8),
      Row(children: [
        Expanded(
          child: TextFormField(
            controller: _driverAmount,
            decoration: const InputDecoration(labelText: 'Сумма, ₽'),
            keyboardType: TextInputType.number,
            onChanged: (_) => _touchedDriver = true,
          ),
        ),
        const SizedBox(width: 12),
        SizedBox(
          width: 90,
          child: TextFormField(
            controller: _driverPercent,
            decoration: const InputDecoration(labelText: '%'),
            keyboardType: TextInputType.number,
            onChanged: (_) => _recalc(),
          ),
        ),
      ]),
    ];
  }
}
