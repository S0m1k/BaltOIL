import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/theme.dart';
import '../auth/auth_repository.dart';
import '../common/copyable_phone.dart';
import '../tariffs/tariffs_repository.dart';
import 'clients_repository.dart';

class ClientsScreen extends StatefulWidget {
  const ClientsScreen({super.key, required this.user});

  final CurrentUser user;

  @override
  State<ClientsScreen> createState() => _ClientsScreenState();
}

class _ClientsScreenState extends State<ClientsScreen> {
  List<ClientItem> _all = [];
  bool _loading = true;
  String? _error;
  String _query = '';

  /// Фильтр Все/Разовые/Зарегистрированные (веб clients-kind-filter).
  bool? _oneOffFilter; // null=все, true=разовые, false=зарегистрированные

  /// Дата последней доставки по клиентам (веб _lastDeliveryByClient).
  Map<String, DateTime> _lastDelivery = const {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      // Дата последней доставки — не блокирует список при недоступности
      // order_service (как на вебе).
      final results = await Future.wait([
        ClientsRepository.instance
            .list(includeInactive: true, oneOff: _oneOffFilter),
        ClientsRepository.instance
            .lastDeliveryByClient()
            .catchError((Object _) => <String, DateTime>{}),
      ]);
      if (!mounted) return;
      setState(() {
        _all = results[0] as List<ClientItem>;
        _lastDelivery = results[1] as Map<String, DateTime>;
        _loading = false;
      });
    } on Object catch (e) {
      if (!mounted) return;
      setState(() {
        _error = apiErrorMessage(e);
        _loading = false;
      });
    }
  }

  List<ClientItem> get _filtered {
    final q = _query.toLowerCase().trim();
    if (q.isEmpty) return _all;
    return _all.where((c) {
      return c.fullName.toLowerCase().contains(q) ||
          (c.email?.toLowerCase().contains(q) ?? false) ||
          (c.phone?.contains(q) ?? false) ||
          (c.clientNumber?.toString().contains(q) ?? false);
    }).toList();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;

    if (_loading) {
      return Center(
        child: CircularProgressIndicator(color: colors.primary),
      );
    }

    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.error_outline_rounded, size: 48, color: colors.red),
              const SizedBox(height: 12),
              Text(
                _error!,
                textAlign: TextAlign.center,
                style: TextStyle(color: colors.text2),
              ),
              const SizedBox(height: 16),
              FilledButton.icon(
                onPressed: _load,
                icon: const Icon(Icons.refresh_rounded),
                label: const Text('Повторить'),
              ),
            ],
          ),
        ),
      );
    }

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 8),
          child: TextField(
            onChanged: (v) => setState(() => _query = v),
            decoration: InputDecoration(
              hintText: 'Поиск клиентов…',
              hintStyle: TextStyle(color: colors.text3),
              prefixIcon: Icon(Icons.search_rounded, color: colors.text3),
              contentPadding:
                  const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            ),
          ),
        ),
        // Фильтр Все/Разовые/Зарегистрированные (веб clients-kind-filter).
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 0, 12, 4),
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: [
                for (final (label, value) in const [
                  ('Все клиенты', null),
                  ('⭐ Разовые', true),
                  ('Зарегистрированные', false),
                ]) ...[
                  ChoiceChip(
                    label: Text(label, style: const TextStyle(fontSize: 12)),
                    selected: _oneOffFilter == value,
                    onSelected: (_) {
                      _oneOffFilter = value;
                      _load();
                    },
                  ),
                  const SizedBox(width: 6),
                ],
              ],
            ),
          ),
        ),
        Expanded(
          child: RefreshIndicator(
            onRefresh: _load,
            color: colors.primary,
            child: _filtered.isEmpty
                ? ListView(
                    children: [
                      SizedBox(height: MediaQuery.of(context).size.height * 0.25),
                      Center(
                        child: Text(
                          _query.isEmpty
                              ? 'Нет клиентов'
                              : 'Ничего не найдено',
                          style: TextStyle(color: colors.text3, fontSize: 15),
                        ),
                      ),
                    ],
                  )
                : ListView.separated(
                    padding: const EdgeInsets.fromLTRB(12, 0, 12, 24),
                    itemCount: _filtered.length,
                    separatorBuilder: (_, _) => const SizedBox(height: 6),
                    itemBuilder: (context, i) {
                      final c = _filtered[i];
                      return _ClientCard(
                        client: c,
                        lastDelivery: _lastDelivery[c.id],
                        onTap: () => _openDetail(context, c),
                      );
                    },
                  ),
          ),
        ),
      ],
    );
  }

  void _openDetail(BuildContext context, ClientItem c) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => _ClientDetailPage(clientId: c.id, title: c.fullName),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Client card widget
// ---------------------------------------------------------------------------

class _ClientCard extends StatelessWidget {
  const _ClientCard({
    required this.client,
    required this.onTap,
    this.lastDelivery,
  });

  final ClientItem client;
  final VoidCallback onTap;
  final DateTime? lastDelivery;

  String _fmtDate(DateTime d) =>
      '${d.day.toString().padLeft(2, '0')}.${d.month.toString().padLeft(2, '0')}.${d.year}';

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          child: Row(
            children: [
              // Active indicator dot
              Container(
                width: 8,
                height: 8,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: client.isActive ? colors.accent : colors.text3,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            client.fullName,
                            style: TextStyle(
                              fontWeight: FontWeight.w600,
                              color: colors.text,
                              fontSize: 14,
                            ),
                          ),
                        ),
                        if (client.isOneOff)
                          Container(
                            margin: const EdgeInsets.only(right: 6),
                            padding: const EdgeInsets.symmetric(
                                horizontal: 5, vertical: 1),
                            decoration: BoxDecoration(
                              border: Border.all(
                                  color: const Color(0xFFD97706)),
                              borderRadius: BorderRadius.circular(4),
                            ),
                            child: const Text(
                              '⭐ разовый',
                              style: TextStyle(
                                fontSize: 10,
                                color: Color(0xFFD97706),
                              ),
                            ),
                          ),
                        if (client.clientNumber != null)
                          Text(
                            '#${client.clientNumber}',
                            style: TextStyle(
                              color: colors.text3,
                              fontSize: 12,
                            ),
                          ),
                      ],
                    ),
                    if (client.email != null && client.email!.isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Text(
                        client.email!,
                        style: TextStyle(color: colors.text2, fontSize: 12),
                      ),
                    ],
                    if (client.phone != null && client.phone!.isNotEmpty) ...[
                      const SizedBox(height: 2),
                      CopyablePhone(
                        client.phone,
                        style: TextStyle(color: colors.text3, fontSize: 12),
                      ),
                    ],
                    if (lastDelivery != null) ...[
                      const SizedBox(height: 2),
                      Text(
                        'Последняя доставка: ${_fmtDate(lastDelivery!)}',
                        style: TextStyle(color: colors.text3, fontSize: 11),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Icon(
                Icons.chevron_right_rounded,
                color: colors.text3,
                size: 20,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Client detail page (pushed on tap)
// ---------------------------------------------------------------------------

class _ClientDetailPage extends StatefulWidget {
  const _ClientDetailPage({required this.clientId, required this.title});

  final String clientId;
  final String title;

  @override
  State<_ClientDetailPage> createState() => _ClientDetailPageState();
}

class _ClientDetailPageState extends State<_ClientDetailPage> {
  ClientDetail? _detail;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final d = await ClientsRepository.instance.getDetail(widget.clientId);
      if (!mounted) return;
      setState(() {
        _detail = d;
        _loading = false;
      });
    } on Object catch (e) {
      if (!mounted) return;
      setState(() {
        _error = apiErrorMessage(e);
        _loading = false;
      });
    }
  }

  /// Настройки клиента staff'ом (веб promptClientSettings): тариф,
  /// «В долг», ВЫКЛ мессенджер, «Только чаты» (правки 2026-07-14).
  Future<void> _openSettings() async {
    final detail = _detail;
    if (detail == null) return;
    List<Tariff> tariffs = const [];
    try {
      tariffs = (await TariffsRepository.instance.list())
          .where((t) => !t.isArchived)
          .toList();
    } on Object {
      // Селект тарифа останется с одним пунктом «базовый».
    }
    if (!mounted) return;
    final p = detail.profile;
    String? tariffId = p?.tariffId;
    if (tariffId != null && !tariffs.any((t) => t.id == tariffId)) {
      tariffId = null;
    }
    bool credit = p?.creditAllowed ?? false;
    bool msgBlocked = p?.messengerBlocked ?? false;
    bool chatsOnly = p?.chatsOnly ?? false;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          title: Text('Настройки клиента: ${detail.fullName}'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                DropdownButtonFormField<String?>(
                  initialValue: tariffId,
                  isExpanded: true,
                  items: [
                    const DropdownMenuItem<String?>(
                        value: null, child: Text('— базовый —')),
                    for (final t in tariffs)
                      DropdownMenuItem<String?>(
                        value: t.id,
                        child: Text(
                          '${t.name}${t.isDefault ? ' (базовый)' : ''}',
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                  ],
                  onChanged: (v) => setDialogState(() => tariffId = v),
                  decoration: const InputDecoration(
                    labelText: 'Тариф',
                    helperText: 'Пустое значение = базовый тариф',
                  ),
                ),
                const SizedBox(height: 8),
                CheckboxListTile(
                  value: credit,
                  onChanged: (v) =>
                      setDialogState(() => credit = v ?? false),
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                  title: const Text('Разрешить тип оплаты «В долг»',
                      style: TextStyle(fontSize: 14)),
                ),
                CheckboxListTile(
                  value: msgBlocked,
                  onChanged: (v) =>
                      setDialogState(() => msgBlocked = v ?? false),
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                  title: const Text('ВЫКЛ мессенджер (доступ ограничен)',
                      style: TextStyle(fontSize: 14)),
                  subtitle: const Text(
                    'Клиент не сможет писать в чаты и не будет находиться '
                    'по номеру телефона. Писать ему смогут только сотрудники.',
                    style: TextStyle(fontSize: 11),
                  ),
                ),
                CheckboxListTile(
                  value: chatsOnly,
                  onChanged: (v) =>
                      setDialogState(() => chatsOnly = v ?? false),
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                  title: const Text('Только чаты',
                      style: TextStyle(fontSize: 14)),
                  subtitle: const Text(
                    'Клиент увидит в системе только мессенджер: без заявок, '
                    'документов и прочего. Создание заявок таким клиентом '
                    'запрещено (менеджер может оформить заявку на него).',
                    style: TextStyle(fontSize: 11),
                  ),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: const Text('Отмена'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(ctx).pop(true),
              child: const Text('Сохранить'),
            ),
          ],
        ),
      ),
    );
    if (ok != true) return;
    try {
      await ClientsRepository.instance.updateSettings(
        widget.clientId,
        tariffId: tariffId,
        creditAllowed: credit,
        messengerBlocked: msgBlocked,
        chatsOnly: chatsOnly,
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Настройки клиента сохранены')),
      );
      _load();
    } on Object catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(apiErrorMessage(e)),
        backgroundColor: Colors.red.shade700,
      ));
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.title),
        actions: [
          if (_detail != null)
            IconButton(
              tooltip: 'Настройки клиента',
              icon: const Icon(Icons.settings_outlined),
              onPressed: _openSettings,
            ),
        ],
      ),
      body: _loading
          ? Center(child: CircularProgressIndicator(color: colors.primary))
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.error_outline_rounded,
                            size: 48, color: colors.red),
                        const SizedBox(height: 12),
                        Text(
                          _error!,
                          textAlign: TextAlign.center,
                          style: TextStyle(color: colors.text2),
                        ),
                        const SizedBox(height: 16),
                        FilledButton.icon(
                          onPressed: _load,
                          icon: const Icon(Icons.refresh_rounded),
                          label: const Text('Повторить'),
                        ),
                      ],
                    ),
                  ),
                )
              : RefreshIndicator(
                  onRefresh: _load,
                  color: colors.primary,
                  child: _ClientDetailBody(detail: _detail!),
                ),
    );
  }
}

class _ClientDetailBody extends StatelessWidget {
  const _ClientDetailBody({required this.detail});

  final ClientDetail detail;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final p = detail.profile;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        // Header card
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      width: 10,
                      height: 10,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color:
                            detail.isActive ? colors.accent : colors.text3,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        detail.fullName,
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w700,
                          color: colors.text,
                        ),
                      ),
                    ),
                    if (detail.clientNumber != null)
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: colors.primaryDim,
                          borderRadius: BorderRadius.circular(20),
                        ),
                        child: Text(
                          '#${detail.clientNumber}',
                          style: TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                            color: colors.primary,
                          ),
                        ),
                      ),
                  ],
                ),
                if (detail.email != null && detail.email!.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  _InfoRow(
                    icon: Icons.email_outlined,
                    value: detail.email!,
                    colors: colors,
                  ),
                ],
                if (detail.phone != null && detail.phone!.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  _InfoRow(
                    icon: Icons.phone_outlined,
                    colors: colors,
                    child: CopyablePhone(
                      detail.phone,
                      style: TextStyle(fontSize: 13, color: colors.text2),
                    ),
                  ),
                ],
                const SizedBox(height: 8),
                _InfoRow(
                  icon: Icons.person_outline_rounded,
                  value: detail.isActive ? 'Активен' : 'Неактивен',
                  colors: colors,
                  valueColor:
                      detail.isActive ? colors.accent : colors.text3,
                ),
              ],
            ),
          ),
        ),

        // Profile / requisites
        if (p != null) ...[
          const SizedBox(height: 12),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    p.clientType == 'company'
                        ? 'Реквизиты юрлица'
                        : 'Профиль',
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                      color: colors.text3,
                      letterSpacing: 0.5,
                    ),
                  ),
                  const SizedBox(height: 12),
                  if (p.companyName != null && p.companyName!.isNotEmpty)
                    _ReqRow(
                        label: 'Организация',
                        value: p.companyName!,
                        colors: colors),
                  if (p.inn != null && p.inn!.isNotEmpty)
                    _ReqRow(label: 'ИНН', value: p.inn!, colors: colors),
                  if (p.kpp != null && p.kpp!.isNotEmpty)
                    _ReqRow(label: 'КПП', value: p.kpp!, colors: colors),
                  if (p.ogrn != null && p.ogrn!.isNotEmpty)
                    _ReqRow(label: 'ОГРН', value: p.ogrn!, colors: colors),
                  if (p.legalAddress != null && p.legalAddress!.isNotEmpty)
                    _ReqRow(
                        label: 'Юр. адрес',
                        value: p.legalAddress!,
                        colors: colors),
                  if (p.deliveryAddress != null &&
                      p.deliveryAddress!.isNotEmpty)
                    _ReqRow(
                        label: 'Адрес доставки',
                        value: p.deliveryAddress!,
                        colors: colors),
                  if (p.bankName != null && p.bankName!.isNotEmpty)
                    _ReqRow(
                        label: 'Банк', value: p.bankName!, colors: colors),
                  if (p.bankAccount != null && p.bankAccount!.isNotEmpty)
                    _ReqRow(
                        label: 'Р/с', value: p.bankAccount!, colors: colors),
                  if (p.billingEmail != null && p.billingEmail!.isNotEmpty)
                    _ReqRow(
                        label: 'Billing email',
                        value: p.billingEmail!,
                        colors: colors),
                  if (p.creditAllowed) ...[
                    _ReqRow(
                        label: 'Кредит',
                        value: p.creditLimit != null
                            ? '${p.creditLimit!.toStringAsFixed(0)} ₽'
                            : 'Да',
                        colors: colors),
                  ],
                ],
              ),
            ),
          ),
        ],

        const SizedBox(height: 12),
        // TODO: Documents tab — GET /orders?client_id=... list
        // TODO: Payments tab — order payment history
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Заявки и оплаты',
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    color: colors.text3,
                    letterSpacing: 0.5,
                  ),
                ),
                const SizedBox(height: 10),
                Text(
                  'TODO: история заявок и оплат клиента',
                  style: TextStyle(color: colors.text3, fontSize: 13),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({
    required this.icon,
    required this.colors,
    this.value,
    this.valueColor,
    this.child,
  }) : assert(value != null || child != null, 'Provide value or child');

  final IconData icon;
  final String? value;
  final AppColors colors;
  final Color? valueColor;

  /// Optional widget rendered instead of [value] text.
  final Widget? child;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(icon, size: 16, color: colors.text3),
        const SizedBox(width: 6),
        Expanded(
          child: child ??
              Text(
                value!,
                style: TextStyle(
                  fontSize: 13,
                  color: valueColor ?? colors.text2,
                ),
              ),
        ),
      ],
    );
  }
}

class _ReqRow extends StatelessWidget {
  const _ReqRow({
    required this.label,
    required this.value,
    required this.colors,
  });

  final String label;
  final String value;
  final AppColors colors;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 120,
            child: Text(
              label,
              style: TextStyle(fontSize: 12, color: colors.text3),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: TextStyle(fontSize: 13, color: colors.text),
            ),
          ),
        ],
      ),
    );
  }
}
