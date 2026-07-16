import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../auth/auth_repository.dart';
import '../organizations/organizations_repository.dart';
import 'order_models.dart';
import 'orders_repository.dart';

/// Подписи типов оплаты (веб PAYMENT_TYPE_LABELS_ALL).
const _kPaymentLabels = <String, String>{
  'on_delivery': 'По факту (при прибытии)',
  'prepaid': 'Предоплата',
  'trade_credit': 'Товарный кредит',
  'postpaid': 'Постоплата (по счёту)',
  'debt': 'В долг',
};

class OrderCreateScreen extends StatefulWidget {
  const OrderCreateScreen({super.key, required this.user, this.duplicateFrom});

  final CurrentUser user;

  /// Заявка-исходник для дублирования (веб duplicateOrder, F1 2026-06-24):
  /// форма открывается с предзаполненными полями — например, чтобы разбить
  /// крупную заявку на две.
  final OrderDetail? duplicateFrom;

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

  // Тип оплаты (веб renderPaymentRadios): для клиентов individual/company
  // выбор скрыт — первый доступный тип подставляется автоматически.
  List<String> _paymentChoices = const ['on_delivery', 'prepaid'];
  bool _paymentHidden = false;

  // «Оформить от имени» — организации клиента (веб c-organization).
  List<Organization> _orgs = const [];
  String? _organizationId; // null = «Физлицо (на себя)»

  // Сохранённые объекты доставки (веб c-saved-object).
  List<ClientObject> _savedObjects = const [];

  // Поля менеджера/админа.
  bool get _isStaff =>
      widget.user.role == 'manager' || widget.user.role == 'admin';
  List<UserBrief>? _clients;
  List<UserBrief>? _drivers;
  String? _clientId;
  String? _driverId; // null = пул («Все водители»)
  bool _isTtnL = false;
  bool _allowUnpaid = false;

  // Разовый клиент (веб __oneoff__, правки 2026-07-11): имя+телефон,
  // всегда физлицо с оплатой по факту; дедуп по номеру на бэке.
  static const _kOneOffClientId = '__oneoff__';
  final _oneOffName = TextEditingController();
  final _oneOffPhone = TextEditingController();
  bool get _isOneOff => _clientId == _kOneOffClientId;

  @override
  void initState() {
    super.initState();
    _loadFuelTypes();
    if (_isStaff) {
      _loadStaffLists();
    } else {
      // Клиент: свои организации/объекты/типы оплаты сразу.
      _loadClientContext(widget.user.id, isSelf: true);
    }
    // Дублирование: предзаполняем поля исходной заявки (веб duplicateOrder).
    final src = widget.duplicateFrom;
    if (src != null) {
      _fuelCode = src.fuelType;
      _volume.text = src.volumeRequested.toStringAsFixed(0);
      _address.text = src.deliveryAddress;
      _contactName.text = src.contactPersonName ?? '';
      _contactPhone.text = src.contactPersonPhone ?? '';
      _comment.text = src.clientComment ?? '';
      if (src.paymentType != null) _paymentType = src.paymentType!;
      if (_isStaff && src.clientId != null) {
        _clientId = src.clientId;
        _managerComment.text = src.managerComment ?? '';
        _loadClientContext(src.clientId!, isSelf: false);
      }
    }
  }

  /// Организации + сохранённые объекты + типы оплаты выбранного клиента.
  /// Ошибки не блокируют форму (как на вебе) — просто прячем блоки.
  Future<void> _loadClientContext(String clientId,
      {required bool isSelf}) async {
    try {
      final orgs = await OrganizationsRepository.instance
          .list(userId: isSelf ? null : clientId);
      if (mounted) {
        setState(() {
          _orgs = orgs;
          _organizationId = null;
        });
      }
    } on Object catch (_) {
      if (mounted) setState(() => _orgs = const []);
    }
    try {
      final objs = await OrdersRepository.instance
          .clientObjects(clientId: isSelf ? null : clientId);
      if (mounted) setState(() => _savedObjects = objs);
    } on Object catch (_) {
      if (mounted) setState(() => _savedObjects = const []);
    }
    try {
      final opts = await OrdersRepository.instance.paymentOptions(clientId);
      if (!mounted) return;
      setState(() {
        final types =
            opts.types.isEmpty ? const ['on_delivery'] : opts.types;
        _paymentChoices = types;
        // Веб: физ и юр лицам выбор скрыт, первый тип — автоматически.
        _paymentHidden = opts.clientType == 'individual' ||
            opts.clientType == 'company';
        if (_paymentHidden || !types.contains(_paymentType)) {
          _paymentType = types.first;
        }
      });
    } on Object catch (_) {
      // Оставляем статические дефолты — не блокируем создание заявки.
    }
  }

  @override
  void dispose() {
    _volume.dispose();
    _address.dispose();
    _comment.dispose();
    _contactName.dispose();
    _contactPhone.dispose();
    _managerComment.dispose();
    _oneOffName.dispose();
    _oneOffPhone.dispose();
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
      var clientId = _isStaff ? _clientId : null;
      var contactName = _contactName.text.trim();
      var contactPhone = _contactPhone.text.trim();
      // Разовый клиент (веб __oneoff__): создаём/находим по телефону
      // перед заявкой; контакт приёмки по умолчанию — сам клиент.
      if (_isStaff && _isOneOff) {
        final ooName = _oneOffName.text.trim();
        final ooPhone = _oneOffPhone.text.trim();
        final oo = await AuthRepository.instance.createOneOffClient(
          fullName: ooName,
          phone: ooPhone,
        );
        clientId = oo['id'] as String;
        if (oo['is_one_off'] != true && mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(
                'Телефон уже в базе — заявка на клиента ${oo['full_name']}'),
          ));
        }
        if (contactName.isEmpty) contactName = ooName;
        if (contactPhone.isEmpty) contactPhone = ooPhone;
      }
      await OrdersRepository.instance.create(
        fuelType: _fuelCode!,
        volume: double.parse(_volume.text.replaceAll(',', '.')),
        address: _address.text.trim(),
        paymentType: _paymentType,
        desiredDate: _desiredDate,
        comment: _comment.text.trim(),
        contactName: contactName,
        contactPhone: contactPhone,
        clientId: clientId,
        managerComment: _isStaff ? _managerComment.text.trim() : null,
        driverId: _isStaff ? _driverId : null,
        isTtnL: _isStaff && _isTtnL,
        allowDeliveryUnpaid: _isStaff && _allowUnpaid,
        organizationId: _organizationId,
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
      appBar: AppBar(
        title: Text(widget.duplicateFrom == null
            ? 'Новая заявка на топливо'
            : 'Новая заявка (дублирована из '
                '№${widget.duplicateFrom!.orderNumber})'),
      ),
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
                  // «Оформить от имени» — показывается, если у клиента есть
                  // организации (веб c-org-group).
                  if (_orgs.isNotEmpty) ...[
                    DropdownButtonFormField<String?>(
                      key: ValueKey('org-${_orgs.length}-$_organizationId'),
                      initialValue: _organizationId,
                      isExpanded: true,
                      items: [
                        const DropdownMenuItem<String?>(
                            value: null, child: Text('Физлицо (на себя)')),
                        for (final o in _orgs)
                          DropdownMenuItem<String?>(
                            value: o.id,
                            child: Text(
                              o.inn == null
                                  ? o.companyName
                                  : '${o.companyName} (ИНН ${o.inn})',
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                      ],
                      onChanged: (v) => setState(() => _organizationId = v),
                      decoration: const InputDecoration(
                          labelText: 'Оформить от имени'),
                    ),
                    const SizedBox(height: 16),
                  ],
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
                    // Staff не ограничен 300 л (веб-фикс 1980084) —
                    // минимум остаётся клиентам и водителям.
                    decoration: InputDecoration(
                        labelText: _isStaff
                            ? 'Объём (литры)'
                            : 'Объём (литры, min 300)'),
                    validator: (v) {
                      final n = double.tryParse((v ?? '').replaceAll(',', '.'));
                      if (n == null || n <= 0) return 'Укажите объём';
                      if (!_isStaff && n < 300) {
                        return 'Минимальный объём — 300 литров';
                      }
                      return null;
                    },
                  ),
                  const SizedBox(height: 16),
                  // Сохранённые объекты доставки клиента (веб c-saved-object):
                  // выбор подставляет адрес в поле ниже.
                  if (_savedObjects.isNotEmpty) ...[
                    DropdownButtonFormField<String?>(
                      key: ValueKey('obj-${_savedObjects.length}'),
                      initialValue: null,
                      isExpanded: true,
                      items: [
                        const DropdownMenuItem<String?>(
                            value: null,
                            child: Text('— сохранённые объекты —')),
                        for (final o in _savedObjects)
                          DropdownMenuItem<String?>(
                            value: o.id,
                            child: Text(o.label,
                                overflow: TextOverflow.ellipsis),
                          ),
                      ],
                      onChanged: (id) {
                        if (id == null) return;
                        final obj = _savedObjects
                            .where((o) => o.id == id)
                            .firstOrNull;
                        if (obj != null) {
                          setState(
                              () => _address.text = obj.deliveryAddress);
                        }
                      },
                      decoration: const InputDecoration(
                          labelText: 'Сохранённые объекты'),
                    ),
                    const SizedBox(height: 16),
                  ],
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
                  // Тип оплаты: для физ/юр лиц скрыт (веб renderPaymentRadios) —
                  // первый доступный тип выбран автоматически.
                  if (!_paymentHidden) ...[
                    Text('Тип оплаты',
                        style: Theme.of(context).textTheme.bodySmall),
                    RadioGroup<String>(
                      groupValue: _paymentType,
                      onChanged: (v) =>
                          setState(() => _paymentType = v ?? 'on_delivery'),
                      child: Column(
                        children: [
                          for (final pt in _paymentChoices)
                            RadioListTile<String>(
                              value: pt,
                              dense: true,
                              title: Text(_kPaymentLabels[pt] ?? pt),
                            ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 8),
                  ],
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
      // Клиент* — обязателен для staff. Первый пункт — «⭐ Разовый клиент»
      // (веб __oneoff__): имя+телефон вместо выбора из базы.
      DropdownButtonFormField<String>(
        initialValue: _clientId,
        isExpanded: true,
        items: [
          const DropdownMenuItem(
              value: _kOneOffClientId,
              child: Text('⭐ Разовый клиент (имя + телефон)')),
          for (final c in clients ?? const <UserBrief>[])
            DropdownMenuItem(
                value: c.id,
                child: Text(c.label, overflow: TextOverflow.ellipsis)),
        ],
        onChanged: clients == null
            ? null
            : (v) {
                setState(() {
                  _clientId = v;
                  if (v == _kOneOffClientId) {
                    // Разовый — всегда физлицо, оплата по факту;
                    // организаций и объектов у него ещё нет.
                    _orgs = const [];
                    _organizationId = null;
                    _savedObjects = const [];
                    _paymentChoices = const ['on_delivery'];
                    _paymentType = 'on_delivery';
                    _paymentHidden = true;
                  }
                });
                // Подгружаем организации/объекты/типы оплаты выбранного
                // клиента — как на вебе при смене c-client-id.
                if (v != null && v != _kOneOffClientId) {
                  _loadClientContext(v, isSelf: false);
                }
              },
        decoration: InputDecoration(
          labelText: 'Клиент *',
          hintText: clients == null ? 'Загрузка…' : 'Выберите клиента',
        ),
        validator: (v) => (_isStaff && v == null) ? 'Выберите клиента' : null,
      ),
      if (_isOneOff) ...[
        const SizedBox(height: 16),
        TextFormField(
          controller: _oneOffName,
          decoration: const InputDecoration(
            labelText: 'Имя разового клиента *',
            hintText: 'Иван Петров',
          ),
          validator: (v) => _isOneOff && (v ?? '').trim().isEmpty
              ? 'Укажите имя разового клиента'
              : null,
        ),
        const SizedBox(height: 16),
        TextFormField(
          controller: _oneOffPhone,
          keyboardType: TextInputType.phone,
          decoration: const InputDecoration(
            labelText: 'Телефон *',
            hintText: '+7 999 000 00 00',
          ),
          validator: (v) => _isOneOff && (v ?? '').trim().isEmpty
              ? 'Укажите телефон разового клиента'
              : null,
        ),
        const SizedBox(height: 6),
        Text(
          'Разовый клиент — всегда физлицо, оплата по факту. Если телефон '
          'уже есть в базе — заявка привяжется к существующему клиенту.',
          style: TextStyle(
              fontSize: 11, color: Theme.of(context).hintColor),
        ),
      ],
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
