import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../auth/auth_repository.dart';
import '../contracts/contract_sheet.dart';
import '../tariffs/tariffs_repository.dart';
import 'organizations_repository.dart';

/// Организации — «Мои организации» у клиента, «Организации» у staff
/// (веб: раздел orgs, orgCardHTML). Водителю раздел не показывается.
class OrganizationsScreen extends StatefulWidget {
  const OrganizationsScreen({super.key, required this.user});

  final CurrentUser user;

  @override
  State<OrganizationsScreen> createState() => _OrganizationsScreenState();
}

class _OrganizationsScreenState extends State<OrganizationsScreen> {
  late Future<List<Organization>> _future;
  final _searchCtrl = TextEditingController();

  bool get _isStaff =>
      widget.user.role == 'admin' || widget.user.role == 'manager';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  void _load() {
    setState(() {
      _future = OrganizationsRepository.instance.list(
        search: _isStaff ? _searchCtrl.text.trim() : null,
      );
    });
  }

  void _openMembers(Organization org) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (_) => _MembersSheet(org: org, isStaff: _isStaff),
    );
  }

  // Договор организации (веб openOrgContract) — видят staff и клиент-участник.
  void _openContract(Organization org) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (_) => ContractSheet(orgId: org.id, isStaff: _isStaff),
    );
  }

  void _openRegistry() {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (_) => const ContractsRegistrySheet(),
    );
  }

  bool get _isAdmin => widget.user.role == 'admin';
  bool get _isClient => widget.user.role == 'client';

  void _err(Object e) {
    if (mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
    }
  }

  /// Создание организации по ИНН с автозаполнением из DaData (веб promptCreateOrg).
  Future<void> _createOrg() async {
    final inn = TextEditingController();
    final name = TextEditingController();
    final kpp = TextEditingController();
    final address = TextEditingController();
    final bik = TextEditingController();
    final account = TextEditingController();
    bool looking = false;

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setD) => AlertDialog(
          title: const Text('Новая организация'),
          content: SizedBox(
            width: double.maxFinite,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  TextField(
                    controller: inn,
                    keyboardType: TextInputType.number,
                    decoration: InputDecoration(
                      labelText: 'ИНН *',
                      helperText: 'Введите ИНН — реквизиты подтянутся из ФНС',
                      suffixIcon: looking
                          ? const Padding(
                              padding: EdgeInsets.all(12),
                              child: SizedBox(
                                width: 16,
                                height: 16,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              ),
                            )
                          : IconButton(
                              icon: const Icon(Icons.search),
                              onPressed: () async {
                                final v = inn.text.trim();
                                if (v.length < 10) return;
                                setD(() => looking = true);
                                try {
                                  final r = await OrganizationsRepository
                                      .instance
                                      .lookupInn(v);
                                  if (r != null) {
                                    name.text = r.companyName ?? name.text;
                                    kpp.text = r.kpp ?? kpp.text;
                                    address.text =
                                        r.legalAddress ?? address.text;
                                  } else if (ctx.mounted) {
                                    ScaffoldMessenger.of(ctx).showSnackBar(
                                      const SnackBar(
                                        content: Text(
                                          'Не найдено — заполните вручную',
                                        ),
                                      ),
                                    );
                                  }
                                } on Object catch (e) {
                                  _err(e);
                                } finally {
                                  setD(() => looking = false);
                                }
                              },
                            ),
                    ),
                  ),
                  TextField(
                    controller: name,
                    decoration: const InputDecoration(labelText: 'Название'),
                  ),
                  TextField(
                    controller: kpp,
                    decoration: const InputDecoration(labelText: 'КПП'),
                  ),
                  TextField(
                    controller: address,
                    decoration: const InputDecoration(labelText: 'Юр. адрес'),
                  ),
                  TextField(
                    controller: bik,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(labelText: 'БИК'),
                  ),
                  TextField(
                    controller: account,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: 'Расчётный счёт',
                    ),
                  ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Отмена'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Создать'),
            ),
          ],
        ),
      ),
    );
    if (ok != true || !mounted) return;
    if (inn.text.trim().length < 10) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('ИНН обязателен (10–12 цифр)')),
      );
      return;
    }
    String? orNull(TextEditingController c) =>
        c.text.trim().isEmpty ? null : c.text.trim();
    try {
      await OrganizationsRepository.instance.create({
        'inn': inn.text.trim(),
        if (orNull(name) != null) 'company_name': orNull(name),
        if (orNull(kpp) != null) 'kpp': orNull(kpp),
        if (orNull(address) != null) 'legal_address': orNull(address),
        if (orNull(bik) != null) 'bik': orNull(bik),
        if (orNull(account) != null) 'bank_account': orNull(account),
      });
      _load();
    } on Object catch (e) {
      _err(e);
    }
  }

  /// Правка реквизитов (owner/admin, веб UpdateOrganizationRequest).
  Future<void> _editOrg(Organization o) async {
    final name = TextEditingController(text: o.companyName);
    final address = TextEditingController(text: o.legalAddress ?? '');
    final bik = TextEditingController(text: o.bik ?? '');
    final account = TextEditingController(text: o.bankAccount ?? '');
    final email = TextEditingController(text: o.billingEmail ?? '');
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Реквизиты организации'),
        content: SizedBox(
          width: double.maxFinite,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: name,
                  decoration: const InputDecoration(labelText: 'Название'),
                ),
                TextField(
                  controller: address,
                  decoration: const InputDecoration(labelText: 'Юр. адрес'),
                ),
                TextField(
                  controller: bik,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: 'БИК'),
                ),
                TextField(
                  controller: account,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(
                    labelText: 'Расчётный счёт',
                  ),
                ),
                TextField(
                  controller: email,
                  keyboardType: TextInputType.emailAddress,
                  decoration: const InputDecoration(
                    labelText: 'Email для счетов',
                  ),
                ),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Сохранить'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    String? orNull(TextEditingController c) =>
        c.text.trim().isEmpty ? null : c.text.trim();
    try {
      await OrganizationsRepository.instance.update(o.id, {
        'company_name': orNull(name),
        'legal_address': orNull(address),
        'bik': orNull(bik),
        'bank_account': orNull(account),
        'billing_email': orNull(email),
      });
      _load();
    } on Object catch (e) {
      _err(e);
    }
  }

  /// Тариф/кредит (admin, веб submitOrgCommercial).
  Future<void> _commercial(Organization o) async {
    List<Tariff> tariffs = const [];
    try {
      tariffs = (await TariffsRepository.instance.list())
          .where((t) => !t.isArchived)
          .toList();
    } on Object catch (_) {}
    if (!mounted) return;
    String? tariffId = o.tariffId;
    bool credit = o.creditAllowed;
    final limit = TextEditingController(
      text: o.creditLimit?.toStringAsFixed(0) ?? '',
    );
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setD) => AlertDialog(
          title: Text('Тариф / кредит — ${o.companyName}'),
          content: SizedBox(
            width: double.maxFinite,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                DropdownButtonFormField<String?>(
                  initialValue: tariffs.any((t) => t.id == tariffId)
                      ? tariffId
                      : null,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Тариф'),
                  items: [
                    const DropdownMenuItem<String?>(
                      value: null,
                      child: Text('— базовый —'),
                    ),
                    for (final t in tariffs)
                      DropdownMenuItem<String?>(
                        value: t.id,
                        child: Text(
                          t.isDefault ? '${t.name} (базовый)' : t.name,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                  ],
                  onChanged: (v) => setD(() => tariffId = v),
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  value: credit,
                  onChanged: (v) => setD(() => credit = v),
                  title: const Text('Разрешить оплату «В долг»'),
                ),
                TextField(
                  controller: limit,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(
                    labelText: 'Кредитный лимит, ₽',
                    hintText: 'пусто = без лимита',
                  ),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Отмена'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Сохранить'),
            ),
          ],
        ),
      ),
    );
    if (ok != true || !mounted) return;
    try {
      await OrganizationsRepository.instance.updateCommercial(
        o.id,
        tariffId: tariffId,
        creditAllowed: credit,
        creditLimit: limit.text.trim().isEmpty
            ? null
            : double.tryParse(limit.text.trim().replaceAll(',', '.')),
      );
      _load();
    } on Object catch (e) {
      _err(e);
    }
  }

  Future<void> _archive(Organization o) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Архивировать организацию?'),
        content: Text(
          'Организация «${o.companyName}» будет скрыта. Исторические '
          'заявки и документы сохранятся.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('В архив'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    try {
      await OrganizationsRepository.instance.archive(o.id);
      _load();
    } on Object catch (e) {
      _err(e);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        // Поиск по названию/ИНН — только staff (как на вебе).
        if (_isStaff)
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _searchCtrl,
                    decoration: const InputDecoration(
                      prefixIcon: Icon(Icons.search),
                      hintText: 'Поиск по названию или ИНН',
                      isDense: true,
                    ),
                    onSubmitted: (_) => _load(),
                  ),
                ),
                // Реестр договоров (веб contracts-registry-btn, staff)
                IconButton(
                  tooltip: 'Реестр договоров',
                  icon: const Icon(Icons.receipt_long),
                  onPressed: _openRegistry,
                ),
              ],
            ),
          ),
        // Клиент сам заводит организацию по ИНН (веб «+», promptCreateOrg).
        if (_isClient)
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
            child: SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: _createOrg,
                icon: const Icon(Icons.add, size: 18),
                label: const Text('Добавить организацию'),
              ),
            ),
          ),
        Expanded(
          child: RefreshIndicator(
            onRefresh: () async => _load(),
            child: FutureBuilder<List<Organization>>(
              future: _future,
              builder: (context, snap) {
                if (snap.connectionState != ConnectionState.done) {
                  return const Center(child: CircularProgressIndicator());
                }
                if (snap.hasError) {
                  return ListView(
                    children: [
                      const SizedBox(height: 100),
                      Center(child: Text(apiErrorMessage(snap.error!))),
                      Center(
                        child: TextButton(
                          onPressed: _load,
                          child: const Text('Повторить'),
                        ),
                      ),
                    ],
                  );
                }
                final orgs = snap.data ?? const [];
                if (orgs.isEmpty) {
                  return ListView(
                    children: [
                      const SizedBox(height: 100),
                      Center(
                        child: Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 24),
                          child: Text(
                            _isStaff
                                ? 'Организаций не найдено.'
                                : 'У вас пока нет организаций. Добавьте юрлицо '
                                      'по ИНН в личном кабинете на сайте, чтобы '
                                      'оформлять заявки от его имени.',
                            textAlign: TextAlign.center,
                          ),
                        ),
                      ),
                    ],
                  );
                }
                return ListView.builder(
                  padding: const EdgeInsets.all(12),
                  itemCount: orgs.length,
                  itemBuilder: (context, i) => _OrgCard(
                    org: orgs[i],
                    isStaff: _isStaff,
                    isAdmin: _isAdmin,
                    onMembers: () => _openMembers(orgs[i]),
                    onContract: () => _openContract(orgs[i]),
                    onEdit: () => _editOrg(orgs[i]),
                    onCommercial: _isAdmin ? () => _commercial(orgs[i]) : null,
                    onArchive: () => _archive(orgs[i]),
                  ),
                );
              },
            ),
          ),
        ),
      ],
    );
  }
}

class _OrgCard extends StatelessWidget {
  const _OrgCard({
    required this.org,
    required this.isStaff,
    required this.isAdmin,
    required this.onMembers,
    required this.onContract,
    required this.onEdit,
    required this.onArchive,
    this.onCommercial,
  });

  final Organization org;
  final bool isStaff;
  final bool isAdmin;
  final VoidCallback onMembers;
  final VoidCallback onContract;
  final VoidCallback onEdit;
  final VoidCallback onArchive;
  final VoidCallback? onCommercial;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final muted = theme.textTheme.bodySmall?.copyWith(
      color: theme.colorScheme.onSurfaceVariant,
    );
    final req = [
      if (org.inn != null) 'ИНН ${org.inn}',
      if (org.kpp != null) 'КПП ${org.kpp}',
    ].join(' · ');

    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Text(
                    org.companyName,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                ),
                // Номер как на вебе: O-00001
                Text(
                  'O-${org.orgNumber.toString().padLeft(5, '0')}',
                  style: muted,
                ),
              ],
            ),
            if (req.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(req, style: muted),
              ),
            if (org.legalAddress != null)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(org.legalAddress!, style: muted),
              ),
            if (isStaff)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  (org.creditAllowed ? '✓ кредит разрешён' : 'без кредита') +
                      (org.creditLimit != null
                          ? ' · лимит ${org.creditLimit!.toStringAsFixed(0)} ₽'
                          : ''),
                  style: muted,
                ),
              ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 4,
              children: [
                OutlinedButton(
                  onPressed: onMembers,
                  style: OutlinedButton.styleFrom(
                    visualDensity: VisualDensity.compact,
                  ),
                  child: const Text('Сотрудники'),
                ),
                // Договор — staff и клиент-участник (веб, правки 2026-06-23)
                OutlinedButton(
                  onPressed: onContract,
                  style: OutlinedButton.styleFrom(
                    visualDensity: VisualDensity.compact,
                  ),
                  child: const Text('Договор'),
                ),
                // Реквизиты — owner/admin (веб UpdateOrganizationRequest)
                OutlinedButton(
                  onPressed: onEdit,
                  style: OutlinedButton.styleFrom(
                    visualDensity: VisualDensity.compact,
                  ),
                  child: const Text('Реквизиты'),
                ),
                // Тариф/кредит — только admin (веб submitOrgCommercial)
                if (onCommercial != null)
                  OutlinedButton(
                    onPressed: onCommercial,
                    style: OutlinedButton.styleFrom(
                      visualDensity: VisualDensity.compact,
                    ),
                    child: const Text('Тариф/кредит'),
                  ),
                // Архивировать — owner/admin (веб archiveOrg)
                TextButton(
                  onPressed: onArchive,
                  style: TextButton.styleFrom(
                    visualDensity: VisualDensity.compact,
                    foregroundColor: theme.colorScheme.error,
                  ),
                  child: const Text('Архив'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// Участники организации — bottom sheet (веб: openOrgMembers).
/// Staff может назначить владельцем активного участника с аккаунтом
/// (веб makeOrgOwner, 2026-07-15) — прежний владелец станет сотрудником.
class _MembersSheet extends StatefulWidget {
  const _MembersSheet({required this.org, required this.isStaff});

  final Organization org;
  final bool isStaff;

  @override
  State<_MembersSheet> createState() => _MembersSheetState();
}

class _MembersSheetState extends State<_MembersSheet> {
  late Future<List<OrganizationMember>> _future;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  void _reload() {
    setState(() {
      _future = OrganizationsRepository.instance.members(widget.org.id);
    });
  }

  Future<void> _makeOwner(OrganizationMember m) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Сменить владельца?'),
        content: Text(
          '${m.fullName ?? m.phone ?? 'Участник'} станет владельцем '
          'организации, прежний владелец — сотрудником. Смена владельца '
          'затрагивает права на реквизиты и коммерческие условия.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Сделать владельцем'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    try {
      await OrganizationsRepository.instance
          .makeOwner(widget.org.id, m.id);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Владелец организации изменён')),
      );
      _reload();
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
    return SafeArea(
      child: FutureBuilder<List<OrganizationMember>>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const SizedBox(
              height: 200,
              child: Center(child: CircularProgressIndicator()),
            );
          }
          if (snap.hasError) {
            return SizedBox(
              height: 200,
              child: Center(child: Text(apiErrorMessage(snap.error!))),
            );
          }
          final members = snap.data ?? const [];
          return ListView(
            shrinkWrap: true,
            padding: const EdgeInsets.all(16),
            children: [
              Text(
                'Сотрудники — ${widget.org.companyName}',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 8),
              if (members.isEmpty) const Text('Участников нет'),
              for (final m in members)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(
                    m.memberRole == 'owner' ? Icons.star : Icons.person_outline,
                  ),
                  title: Text(m.fullName ?? m.invitePhone ?? '—'),
                  subtitle: Text(
                    [
                      if (m.memberRole == 'owner') 'владелец',
                      if (m.phone != null) m.phone!,
                      if (m.status != null && m.status != 'active') m.status!,
                    ].join(' · '),
                  ),
                  // Как на вебе: активный участник с аккаунтом, не владелец.
                  trailing: widget.isStaff &&
                          m.memberRole != 'owner' &&
                          m.userId != null &&
                          m.status == 'active'
                      ? TextButton(
                          onPressed: () => _makeOwner(m),
                          child: const Text('Владельцем',
                              style: TextStyle(fontSize: 12)),
                        )
                      : null,
                ),
            ],
          );
        },
      ),
    );
  }
}
