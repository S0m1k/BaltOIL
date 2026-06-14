import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../auth/auth_repository.dart';
import 'order_models.dart';
import 'orders_repository.dart';

class OrderCreateScreen extends StatefulWidget {
  const OrderCreateScreen({super.key, required this.user});

  final CurrentUser user;

  @override
  State<OrderCreateScreen> createState() => _OrderCreateScreenState();
}

class _OrderCreateScreenState extends State<OrderCreateScreen> {
  final _formKey = GlobalKey<FormState>();
  final _volume = TextEditingController();
  final _address = TextEditingController();
  final _comment = TextEditingController();
  final _contactName = TextEditingController();
  final _contactPhone = TextEditingController();
  final _managerComment = TextEditingController();

  List<FuelType>? _fuelTypes;
  String? _fuelCode;
  DateTime? _desiredDate;
  String _paymentType = 'on_delivery'; // как на вебе: «По факту» по умолчанию
  bool _busy = false;
  String? _error;

  // Поля менеджера/админа.
  bool get _isStaff =>
      widget.user.role == 'manager' || widget.user.role == 'admin';
  List<UserBrief>? _clients;
  List<UserBrief>? _drivers;
  String? _clientId;
  String? _driverId; // null = пул («Все водители»)
  bool _isTtnL = false;
  bool _allowUnpaid = false;

  @override
  void initState() {
    super.initState();
    _loadFuelTypes();
    if (_isStaff) _loadStaffLists();
  }

  @override
  void dispose() {
    _volume.dispose();
    _address.dispose();
    _comment.dispose();
    _contactName.dispose();
    _contactPhone.dispose();
    _managerComment.dispose();
    super.dispose();
  }

  Future<void> _loadFuelTypes() async {
    try {
      final types = await OrdersRepository.instance.fuelTypes();
      if (!mounted) return;
      setState(() {
        _fuelTypes = types;
        if (types.isNotEmpty) _fuelCode = types.first.code;
      });
    } on Object catch (e) {
      if (mounted) setState(() => _error = apiErrorMessage(e));
    }
  }

  Future<void> _loadStaffLists() async {
    try {
      final results = await Future.wait([
        AuthRepository.instance.listByRole('client'),
        AuthRepository.instance.listByRole('driver'),
      ]);
      if (!mounted) return;
      setState(() {
        _clients = results[0];
        _drivers = results[1];
      });
    } on Object catch (e) {
      if (mounted) setState(() => _error = apiErrorMessage(e));
    }
  }

  Future<void> _pickDate() async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: now.add(const Duration(days: 1)),
      firstDate: now,
      lastDate: now.add(const Duration(days: 60)),
    );
    if (picked != null) setState(() => _desiredDate = picked);
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate() || _fuelCode == null) return;
    if (_isStaff && _clientId == null) {
      setState(() => _error = 'Выберите клиента');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await OrdersRepository.instance.create(
        fuelType: _fuelCode!,
        volume: double.parse(_volume.text.replaceAll(',', '.')),
        address: _address.text.trim(),
        paymentType: _paymentType,
        desiredDate: _desiredDate,
        comment: _comment.text.trim(),
        contactName: _contactName.text.trim(),
        contactPhone: _contactPhone.text.trim(),
        clientId: _isStaff ? _clientId : null,
        managerComment: _isStaff ? _managerComment.text.trim() : null,
        driverId: _isStaff ? _driverId : null,
        isTtnL: _isStaff && _isTtnL,
        allowDeliveryUnpaid: _isStaff && _allowUnpaid,
      );
      if (mounted) Navigator.of(context).pop(true);
    } on Object catch (e) {
      if (mounted) setState(() => _error = apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final types = _fuelTypes;
    return Scaffold(
      appBar: AppBar(title: const Text('Новая заявка на топливо')),
      body: types == null
          ? Center(
              child: _error == null
                  ? const CircularProgressIndicator()
                  : Text(_error!))
          : Form(
              key: _formKey,
              child: ListView(
                padding: const EdgeInsets.all(20),
                children: [
                  if (_isStaff) ..._staffSection(),
                  DropdownButtonFormField<String>(
                    initialValue: _fuelCode,
                    items: [
                      for (final t in types)
                        DropdownMenuItem(value: t.code, child: Text(t.label)),
                    ],
                    onChanged: (v) => setState(() => _fuelCode = v),
                    decoration: const InputDecoration(labelText: 'Вид топлива'),
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: _volume,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                        labelText: 'Объём (литры, min 300)'),
                    validator: (v) {
                      final n = double.tryParse((v ?? '').replaceAll(',', '.'));
                      if (n == null) return 'Укажите объём';
                      if (n < 300) return 'Минимальный объём — 300 литров';
                      return null;
                    },
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: _address,
                    decoration:
                        const InputDecoration(labelText: 'Адрес доставки'),
                    validator: (v) => (v == null || v.trim().length < 5)
                        ? 'Укажите адрес'
                        : null,
                  ),
                  const SizedBox(height: 16),
                  OutlinedButton.icon(
                    onPressed: _pickDate,
                    icon: const Icon(Icons.calendar_today, size: 18),
                    label: Text(_desiredDate == null
                        ? 'Желаемая дата доставки'
                        : 'Дата: ${_desiredDate!.day}.${_desiredDate!.month}.${_desiredDate!.year}'),
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: _contactName,
                    decoration: const InputDecoration(
                        labelText: 'Контактное лицо для приёмки'),
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: _contactPhone,
                    keyboardType: TextInputType.phone,
                    decoration: const InputDecoration(
                        labelText: 'Телефон контактного лица'),
                  ),
                  const SizedBox(height: 16),
                  Text('Тип оплаты',
                      style: Theme.of(context).textTheme.bodySmall),
                  RadioGroup<String>(
                    groupValue: _paymentType,
                    onChanged: (v) =>
                        setState(() => _paymentType = v ?? 'on_delivery'),
                    child: const Column(
                      children: [
                        RadioListTile<String>(
                          value: 'on_delivery',
                          dense: true,
                          title: Text('По факту (при прибытии)'),
                        ),
                        RadioListTile<String>(
                          value: 'prepaid',
                          dense: true,
                          title: Text('Предоплата'),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 8),
                  TextFormField(
                    controller: _comment,
                    maxLines: 2,
                    decoration: const InputDecoration(
                      labelText: 'Комментарий',
                      hintText: 'Дополнительные пожелания...',
                    ),
                  ),
                  if (_error != null) ...[
                    const SizedBox(height: 12),
                    Text(_error!, style: const TextStyle(color: Colors.red)),
                  ],
                  const SizedBox(height: 24),
                  FilledButton(
                    onPressed: _busy ? null : _submit,
                    child: _busy
                        ? const SizedBox(
                            height: 20,
                            width: 20,
                            child: CircularProgressIndicator(strokeWidth: 2))
                        : const Text('Отправить заявку'),
                  ),
                ],
              ),
            ),
    );
  }

  /// Блок полей, доступных только менеджеру/админу (как `#manager-create-fields`
  /// на вебе): клиент*, комментарий менеджера, водитель, ТТН-Л, долговая заявка.
  List<Widget> _staffSection() {
    final clients = _clients;
    final drivers = _drivers;
    return [
      Text('Параметры менеджера',
          style: Theme.of(context)
              .textTheme
              .titleSmall
              ?.copyWith(fontWeight: FontWeight.w700)),
      const SizedBox(height: 12),
      // Клиент* — обязателен для staff.
      DropdownButtonFormField<String>(
        initialValue: _clientId,
        isExpanded: true,
        items: [
          for (final c in clients ?? const <UserBrief>[])
            DropdownMenuItem(
                value: c.id,
                child: Text(c.label, overflow: TextOverflow.ellipsis)),
        ],
        onChanged:
            clients == null ? null : (v) => setState(() => _clientId = v),
        decoration: InputDecoration(
          labelText: 'Клиент *',
          hintText: clients == null ? 'Загрузка…' : 'Выберите клиента',
        ),
        validator: (v) => (_isStaff && v == null) ? 'Выберите клиента' : null,
      ),
      const SizedBox(height: 16),
      TextFormField(
        controller: _managerComment,
        decoration: const InputDecoration(labelText: 'Комментарий менеджера'),
      ),
      const SizedBox(height: 16),
      // Назначить водителя — по умолчанию пул (null).
      DropdownButtonFormField<String?>(
        initialValue: _driverId,
        isExpanded: true,
        items: [
          const DropdownMenuItem<String?>(
              value: null, child: Text('Все водители (пул)')),
          for (final d in drivers ?? const <UserBrief>[])
            DropdownMenuItem<String?>(
                value: d.id,
                child: Text(d.label, overflow: TextOverflow.ellipsis)),
        ],
        onChanged: drivers == null
            ? null
            : (v) => setState(() {
                  _driverId = v;
                  if (v == null) _isTtnL = false; // ТТН-Л только при водителе
                }),
        decoration: const InputDecoration(labelText: 'Назначить водителя'),
      ),
      // ТТН-Л показываем только если выбран конкретный водитель (как на вебе).
      if (_driverId != null)
        CheckboxListTile(
          value: _isTtnL,
          onChanged: (v) => setState(() => _isTtnL = v ?? false),
          dense: true,
          contentPadding: EdgeInsets.zero,
          controlAffinity: ListTileControlAffinity.leading,
          title: const Text('ТТН-Л (внутренняя заявка)'),
        ),
      CheckboxListTile(
        value: _allowUnpaid,
        onChanged: (v) => setState(() => _allowUnpaid = v ?? false),
        dense: true,
        contentPadding: EdgeInsets.zero,
        controlAffinity: ListTileControlAffinity.leading,
        title: const Text('Долговая заявка (доставка без оплаты)'),
      ),
      const Divider(height: 32),
    ];
  }
}
