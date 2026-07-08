import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../auth/auth_repository.dart';
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
      _future = OrganizationsRepository.instance
          .list(search: _isStaff ? _searchCtrl.text.trim() : null);
    });
  }

  void _openMembers(Organization org) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (_) => _MembersSheet(org: org),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        // Поиск по названию/ИНН — только staff (как на вебе).
        if (_isStaff)
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
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
                  return ListView(children: [
                    const SizedBox(height: 100),
                    Center(child: Text(apiErrorMessage(snap.error!))),
                    Center(
                      child: TextButton(
                          onPressed: _load,
                          child: const Text('Повторить')),
                    ),
                  ]);
                }
                final orgs = snap.data ?? const [];
                if (orgs.isEmpty) {
                  return ListView(children: [
                    const SizedBox(height: 100),
                    Center(
                      child: Padding(
                        padding:
                            const EdgeInsets.symmetric(horizontal: 24),
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
                  ]);
                }
                return ListView.builder(
                  padding: const EdgeInsets.all(12),
                  itemCount: orgs.length,
                  itemBuilder: (context, i) => _OrgCard(
                    org: orgs[i],
                    isStaff: _isStaff,
                    onMembers: () => _openMembers(orgs[i]),
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
    required this.onMembers,
  });

  final Organization org;
  final bool isStaff;
  final VoidCallback onMembers;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final muted = theme.textTheme.bodySmall
        ?.copyWith(color: theme.colorScheme.onSurfaceVariant);
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
                  child: Text(org.companyName,
                      style:
                          const TextStyle(fontWeight: FontWeight.w600)),
                ),
                // Номер как на вебе: O-00001
                Text('O-${org.orgNumber.toString().padLeft(5, '0')}',
                    style: muted),
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
                  org.creditAllowed ? '✓ кредит разрешён' : 'без кредита',
                  style: muted,
                ),
              ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              children: [
                OutlinedButton(
                  onPressed: onMembers,
                  style: OutlinedButton.styleFrom(
                      visualDensity: VisualDensity.compact),
                  child: const Text('Сотрудники'),
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
class _MembersSheet extends StatelessWidget {
  const _MembersSheet({required this.org});

  final Organization org;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: FutureBuilder<List<OrganizationMember>>(
        future: OrganizationsRepository.instance.members(org.id),
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const SizedBox(
                height: 200,
                child: Center(child: CircularProgressIndicator()));
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
              Text('Сотрудники — ${org.companyName}',
                  style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              if (members.isEmpty) const Text('Участников нет'),
              for (final m in members)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(m.memberRole == 'owner'
                      ? Icons.star
                      : Icons.person_outline),
                  title: Text(m.fullName ?? m.invitePhone ?? '—'),
                  subtitle: Text([
                    if (m.memberRole == 'owner') 'владелец',
                    if (m.phone != null) m.phone!,
                    if (m.status != null && m.status != 'active') m.status!,
                  ].join(' · ')),
                ),
            ],
          );
        },
      ),
    );
  }
}
