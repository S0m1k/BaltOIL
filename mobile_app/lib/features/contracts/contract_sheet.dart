import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import 'contracts_repository.dart';

String _fmtDate(DateTime? d) => d == null
    ? '—'
    : '${d.day.toString().padLeft(2, '0')}.'
          '${d.month.toString().padLeft(2, '0')}.${d.year}';

/// Договор организации (веб openOrgContract): номер/дата/статус;
/// staff — правка номера/даты + «Сгенерировать заново», «На почту».
class ContractSheet extends StatefulWidget {
  const ContractSheet({super.key, required this.orgId, required this.isStaff});

  final String orgId;
  final bool isStaff;

  @override
  State<ContractSheet> createState() => _ContractSheetState();
}

class _ContractSheetState extends State<ContractSheet> {
  Contract? _contract;
  String? _error;
  bool _busy = false;
  final _numCtrl = TextEditingController();
  DateTime? _signedAt;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _numCtrl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _contract = null;
      _error = null;
    });
    try {
      final c = await ContractsRepository.instance.byOrganization(widget.orgId);
      if (!mounted) return;
      setState(() {
        _contract = c;
        _numCtrl.text = c.contractNumber;
        _signedAt = c.signedAt;
      });
    } on Object catch (e) {
      if (mounted) setState(() => _error = apiErrorMessage(e));
    }
  }

  Future<void> _regenerate() async {
    final c = _contract;
    if (c == null) return;
    setState(() => _busy = true);
    try {
      await ContractsRepository.instance.regenerate(
        c.id,
        contractNumber: _numCtrl.text.trim().isEmpty
            ? null
            : _numCtrl.text.trim(),
        signedAt: _signedAt?.toIso8601String().substring(0, 10),
      );
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('Договор перевыпущен')));
      await _load();
    } on Object catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _sendEmail() async {
    final c = _contract;
    if (c == null) return;
    setState(() => _busy = true);
    try {
      final to = await ContractsRepository.instance.sendEmail(c.id);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Договор отправлен на ${to ?? 'почту'}')),
      );
    } on Object catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _pickDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _signedAt ?? DateTime.now(),
      firstDate: DateTime(2020),
      lastDate: DateTime.now().add(const Duration(days: 365)),
    );
    if (picked != null) setState(() => _signedAt = picked);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final c = _contract;
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.only(
          left: 16,
          right: 16,
          bottom: MediaQuery.of(context).viewInsets.bottom + 16,
        ),
        child: c == null
            ? SizedBox(
                height: 180,
                child: Center(
                  child: _error == null
                      ? const CircularProgressIndicator()
                      : Text(_error!, textAlign: TextAlign.center),
                ),
              )
            : ListView(
                shrinkWrap: true,
                children: [
                  Text('Договор', style: theme.textTheme.titleMedium),
                  const SizedBox(height: 10),
                  Text(
                    'Номер: ${c.contractNumber}',
                    style: const TextStyle(
                      fontFamily: 'monospace',
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  Text('Дата: ${_fmtDate(c.signedAt ?? c.createdAt)}'),
                  Text(
                    'Статус: ${c.status == 'active' ? 'действующий' : c.status}',
                  ),
                  if (widget.isStaff) ...[
                    const Divider(height: 24),
                    TextField(
                      controller: _numCtrl,
                      decoration: const InputDecoration(labelText: 'Номер'),
                    ),
                    const SizedBox(height: 8),
                    OutlinedButton.icon(
                      onPressed: _busy ? null : _pickDate,
                      icon: const Icon(Icons.calendar_today, size: 16),
                      label: Text(
                        _signedAt == null
                            ? 'Дата договора'
                            : 'Дата: ${_fmtDate(_signedAt)}',
                      ),
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 8,
                      children: [
                        FilledButton.tonal(
                          onPressed: _busy ? null : _regenerate,
                          child: const Text('Сгенерировать заново'),
                        ),
                        OutlinedButton.icon(
                          onPressed: _busy ? null : _sendEmail,
                          icon: const Icon(Icons.mail_outline, size: 16),
                          label: const Text('На почту'),
                        ),
                      ],
                    ),
                  ],
                ],
              ),
      ),
    );
  }
}

/// Реестр договоров (staff, веб openContractsRegistry).
class ContractsRegistrySheet extends StatelessWidget {
  const ContractsRegistrySheet({super.key});

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: FutureBuilder<List<Contract>>(
        future: ContractsRepository.instance.registry(),
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
          final rows = snap.data ?? const [];
          return ListView(
            shrinkWrap: true,
            padding: const EdgeInsets.all(16),
            children: [
              Text(
                'Реестр договоров',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 8),
              if (rows.isEmpty) const Text('Договоров нет.'),
              for (final r in rows)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  dense: true,
                  title: Text(
                    r.contractNumber,
                    style: const TextStyle(fontFamily: 'monospace'),
                  ),
                  subtitle: Text(r.organizationName ?? '—'),
                  trailing: Text(_fmtDate(r.signedAt ?? r.createdAt)),
                ),
            ],
          );
        },
      ),
    );
  }
}
