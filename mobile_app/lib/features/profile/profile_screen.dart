import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/theme.dart';
import '../auth/auth_repository.dart';

/// Экран «Мой профиль».
///
/// Загружает полный профиль через GET /auth/me, отображает поля
/// и позволяет редактировать ФИО, email, телефон и менять пароль.
/// Клиентам-юрлицам доступно также редактирование реквизитов.
/// Роль — только для чтения (chip с roleColor).
class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key, required this.user});

  final CurrentUser user;

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  Map<String, dynamic>? _profile;
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
      final data = await AuthRepository.instance.meFullProfile();
      if (!mounted) return;
      setState(() {
        _profile = data;
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

  void _openEditDialog() {
    final profile = _profile;
    if (profile == null) return;

    final fullNameCtrl =
        TextEditingController(text: profile['full_name'] as String? ?? '');
    final emailCtrl =
        TextEditingController(text: profile['email'] as String? ?? '');
    final phoneCtrl =
        TextEditingController(text: profile['phone'] as String? ?? '');

    final cp = profile['client_profile'] as Map<String, dynamic>?;
    final isIndividualClient = widget.user.role == 'client' &&
        cp != null &&
        cp['client_type'] == 'individual';
    final deliveryCtrl = TextEditingController(
      // cp is guaranteed non-null when isIndividualClient is true (checked above).
      text: isIndividualClient
          ? (cp!['delivery_address'] as String? ?? '')
          : '',
    );

    showDialog<void>(
      context: context,
      builder: (ctx) => _EditDialog(
        profile: profile,
        fullNameCtrl: fullNameCtrl,
        emailCtrl: emailCtrl,
        phoneCtrl: phoneCtrl,
        deliveryCtrl: deliveryCtrl,
        isIndividualClient: isIndividualClient,
        onSaved: _load,
      ),
    );
  }

  void _openPasswordDialog() {
    showDialog<void>(
      context: context,
      builder: (ctx) => const _ChangePasswordDialog(),
    );
  }

  void _openRequisitesDialog() {
    final profile = _profile;
    if (profile == null) return;
    final cp = profile['client_profile'] as Map<String, dynamic>? ?? {};
    showDialog<void>(
      context: context,
      builder: (ctx) => _RequisitesDialog(
        userId: profile['id'] as String,
        cp: cp,
        onSaved: _load,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;

    if (_loading) {
      return Center(child: CircularProgressIndicator(color: colors.primary));
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
              FilledButton(onPressed: _load, child: const Text('Повторить')),
            ],
          ),
        ),
      );
    }

    final profile = _profile!;
    final role = profile['role'] as String? ?? widget.user.role;
    final roleLabel = _roleLabel(role);
    final cp = profile['client_profile'] as Map<String, dynamic>?;
    final isClient = role == 'client';
    final isCompany = cp != null && cp['client_type'] == 'company';

    return RefreshIndicator(
      onRefresh: _load,
      color: colors.primary,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // ── Аватар + имя + роль ────────────────────────────────
          _AvatarHeader(
            fullName: profile['full_name'] as String? ?? '',
            role: role,
            roleLabel: roleLabel,
            colors: colors,
          ),
          const SizedBox(height: 20),

          // ── Карточка основных данных ───────────────────────────
          _SectionCard(
            colors: colors,
            title: 'Мои данные',
            children: [
              _InfoRow(
                label: 'ФИО',
                value: profile['full_name'] as String? ?? '—',
                colors: colors,
              ),
              _InfoRow(
                label: 'Email',
                value: (profile['email'] as String?)?.isNotEmpty == true
                    ? profile['email'] as String
                    : '—',
                colors: colors,
              ),
              _InfoRow(
                label: 'Телефон',
                value: (profile['phone'] as String?)?.isNotEmpty == true
                    ? profile['phone'] as String
                    : '—',
                colors: colors,
              ),
              _InfoRow(
                label: 'Статус',
                value: (profile['is_active'] as bool? ?? true)
                    ? 'Активен'
                    : 'Неактивен',
                valueColor: (profile['is_active'] as bool? ?? true)
                    ? colors.green
                    : colors.red,
                colors: colors,
              ),
            ],
          ),
          const SizedBox(height: 12),

          // ── Кнопки редактирования ─────────────────────────────
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: _openEditDialog,
                  icon: const Icon(Icons.edit_outlined, size: 16),
                  label: const Text('Редактировать'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: colors.primary,
                    side: BorderSide(color: colors.primary),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: _openPasswordDialog,
                  icon: const Icon(Icons.lock_outline, size: 16),
                  label: const Text('Пароль'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: colors.text2,
                    side: BorderSide(color: colors.border),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),

          // ── Карточка профиля клиента ───────────────────────────
          if (isClient && cp != null) ...[
            _SectionCard(
              colors: colors,
              title: isCompany ? 'Реквизиты организации' : 'Клиентский профиль',
              children: [
                _InfoRow(
                  label: 'Тип',
                  value: isCompany ? 'Юридическое лицо' : 'Физическое лицо',
                  colors: colors,
                ),
                if (isCompany) ...[
                  _InfoRow(
                    label: 'Компания',
                    value: cp['company_name'] as String? ?? '—',
                    colors: colors,
                  ),
                  _InfoRow(
                    label: 'ИНН',
                    value: cp['inn'] as String? ?? '—',
                    colors: colors,
                  ),
                  _InfoRow(
                    label: 'КПП',
                    value: cp['kpp'] as String? ?? '—',
                    colors: colors,
                  ),
                  if ((cp['ogrn'] as String?)?.isNotEmpty == true)
                    _InfoRow(
                      label: 'ОГРН',
                      value: cp['ogrn'] as String,
                      colors: colors,
                    ),
                  _InfoRow(
                    label: 'Юр. адрес',
                    value: cp['legal_address'] as String? ?? '—',
                    colors: colors,
                  ),
                  _InfoRow(
                    label: 'БИК',
                    value: cp['bik'] as String? ?? '—',
                    colors: colors,
                  ),
                  _InfoRow(
                    label: 'Расч. счёт',
                    value: cp['bank_account'] as String? ?? '—',
                    colors: colors,
                  ),
                  _InfoRow(
                    label: 'Банк',
                    value: cp['bank_name'] as String? ?? '—',
                    colors: colors,
                  ),
                  _InfoRow(
                    label: 'Корр. счёт',
                    value: cp['correspondent_account'] as String? ?? '—',
                    colors: colors,
                  ),
                  _InfoRow(
                    label: 'Email (доки)',
                    value: cp['billing_email'] as String? ?? '—',
                    colors: colors,
                  ),
                  _InfoRow(
                    label: 'Адрес доставки',
                    value: cp['delivery_address'] as String? ?? '—',
                    colors: colors,
                  ),
                ] else ...[
                  if ((cp['delivery_address'] as String?)?.isNotEmpty == true)
                    _InfoRow(
                      label: 'Адрес доставки',
                      value: cp['delivery_address'] as String,
                      colors: colors,
                    ),
                ],
              ],
            ),
            const SizedBox(height: 12),
            if (isCompany)
              SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  onPressed: _openRequisitesDialog,
                  icon: const Icon(Icons.business_outlined, size: 16),
                  label: const Text('Редактировать реквизиты'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: colors.accent,
                    side: BorderSide(color: colors.accent),
                  ),
                ),
              ),
            const SizedBox(height: 20),
          ],
        ],
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// Вспомогательные виджеты
// ═══════════════════════════════════════════════════════════════

class _AvatarHeader extends StatelessWidget {
  const _AvatarHeader({
    required this.fullName,
    required this.role,
    required this.roleLabel,
    required this.colors,
  });

  final String fullName;
  final String role;
  final String roleLabel;
  final AppColors colors;

  String get _initials {
    final parts = fullName.trim().split(RegExp(r'\s+'));
    if (parts.isEmpty) return '?';
    if (parts.length == 1) return parts[0][0].toUpperCase();
    return '${parts[0][0]}${parts[1][0]}'.toUpperCase();
  }

  @override
  Widget build(BuildContext context) {
    final roleColor = colors.roleColor(role);
    return Column(
      children: [
        CircleAvatar(
          radius: 36,
          backgroundColor: roleColor.withAlpha(30),
          child: Text(
            _initials,
            style: TextStyle(
              color: roleColor,
              fontSize: 24,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
        const SizedBox(height: 10),
        Text(
          fullName.isNotEmpty ? fullName : '—',
          style: TextStyle(
            color: colors.text,
            fontSize: 18,
            fontWeight: FontWeight.w700,
          ),
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: 6),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
          decoration: BoxDecoration(
            color: roleColor.withAlpha(25),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Text(
            roleLabel,
            style: TextStyle(
              color: roleColor,
              fontSize: 12,
              fontWeight: FontWeight.w600,
              letterSpacing: 0.4,
            ),
          ),
        ),
      ],
    );
  }
}

class _SectionCard extends StatelessWidget {
  const _SectionCard({
    required this.colors,
    required this.title,
    required this.children,
  });

  final AppColors colors;
  final String title;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: colors.bg2,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: colors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 8),
            child: Text(
              title,
              style: TextStyle(
                color: colors.text3,
                fontSize: 11,
                fontWeight: FontWeight.w600,
                letterSpacing: 1,
              ),
            ),
          ),
          const Divider(height: 1),
          ...children,
        ],
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({
    required this.label,
    required this.value,
    required this.colors,
    this.valueColor,
  });

  final String label;
  final String value;
  final AppColors colors;
  final Color? valueColor;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        border: Border(bottom: BorderSide(color: colors.border, width: 0.5)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 110,
            child: Text(
              label,
              style: TextStyle(
                color: colors.text3,
                fontSize: 12,
                fontWeight: FontWeight.w500,
              ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: TextStyle(
                color: valueColor ?? colors.text2,
                fontSize: 13,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// Диалог: редактировать ФИО / email / телефон
// ═══════════════════════════════════════════════════════════════

class _EditDialog extends StatefulWidget {
  const _EditDialog({
    required this.profile,
    required this.fullNameCtrl,
    required this.emailCtrl,
    required this.phoneCtrl,
    required this.deliveryCtrl,
    required this.isIndividualClient,
    required this.onSaved,
  });

  final Map<String, dynamic> profile;
  final TextEditingController fullNameCtrl;
  final TextEditingController emailCtrl;
  final TextEditingController phoneCtrl;
  final TextEditingController deliveryCtrl;
  final bool isIndividualClient;
  final VoidCallback onSaved;

  @override
  State<_EditDialog> createState() => _EditDialogState();
}

class _EditDialogState extends State<_EditDialog> {
  final _formKey = GlobalKey<FormState>();
  bool _busy = false;
  String? _error;

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;

    final fullName = widget.fullNameCtrl.text.trim();
    final email = widget.emailCtrl.text.trim();
    final phone = widget.phoneCtrl.text.trim();

    final userId = widget.profile['id'] as String;
    final prevEmail = widget.profile['email'] as String? ?? '';
    final prevPhone = widget.profile['phone'] as String? ?? '';

    final body = <String, dynamic>{
      'full_name': fullName,
    };
    if (email != prevEmail) body['email'] = email.isEmpty ? null : email;
    if (phone != prevPhone && phone.isNotEmpty) body['phone'] = phone;

    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await AuthRepository.instance.updateMe(userId, body);

      if (widget.isIndividualClient) {
        final addr = widget.deliveryCtrl.text.trim();
        final cp = widget.profile['client_profile'] as Map<String, dynamic>?;
        final prevAddr = cp?['delivery_address'] as String? ?? '';
        if (addr != prevAddr) {
          await AuthRepository.instance
              .updateClientProfile(userId, {'delivery_address': addr.isEmpty ? null : addr});
        }
      }

      if (!mounted) return;
      Navigator.of(context).pop();
      widget.onSaved();
    } on Object catch (e) {
      if (!mounted) return;
      setState(() => _error = apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return AlertDialog(
      backgroundColor: colors.bg2,
      title: Text('Мои данные', style: TextStyle(color: colors.text)),
      content: SingleChildScrollView(
        child: Form(
          key: _formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                controller: widget.fullNameCtrl,
                decoration: const InputDecoration(labelText: 'ФИО'),
                validator: (v) =>
                    (v == null || v.trim().isEmpty) ? 'Укажите ФИО' : null,
              ),
              const SizedBox(height: 14),
              TextFormField(
                controller: widget.emailCtrl,
                keyboardType: TextInputType.emailAddress,
                decoration:
                    const InputDecoration(labelText: 'Email', hintText: 'example@mail.ru'),
              ),
              const SizedBox(height: 14),
              TextFormField(
                controller: widget.phoneCtrl,
                keyboardType: TextInputType.phone,
                decoration:
                    const InputDecoration(labelText: 'Телефон', hintText: '+7 900 000 00 00'),
              ),
              if (widget.isIndividualClient) ...[
                const SizedBox(height: 14),
                TextFormField(
                  controller: widget.deliveryCtrl,
                  decoration: const InputDecoration(labelText: 'Адрес доставки'),
                ),
              ],
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(
                  _error!,
                  style: TextStyle(color: colors.red, fontSize: 13),
                ),
              ],
              const SizedBox(height: 4),
              Text(
                'Email и телефон должны быть уникальными.',
                style: TextStyle(color: colors.text3, fontSize: 11),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _busy ? null : () => Navigator.of(context).pop(),
          child: const Text('Отмена'),
        ),
        FilledButton(
          onPressed: _busy ? null : _save,
          child: _busy
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: Colors.white,
                  ),
                )
              : const Text('Сохранить'),
        ),
      ],
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// Диалог: смена пароля
// ═══════════════════════════════════════════════════════════════

class _ChangePasswordDialog extends StatefulWidget {
  const _ChangePasswordDialog();

  @override
  State<_ChangePasswordDialog> createState() => _ChangePasswordDialogState();
}

class _ChangePasswordDialogState extends State<_ChangePasswordDialog> {
  final _formKey = GlobalKey<FormState>();
  final _currentCtrl = TextEditingController();
  final _newCtrl = TextEditingController();
  final _confirmCtrl = TextEditingController();
  bool _busy = false;
  String? _error;
  bool _obscureCurrent = true;
  bool _obscureNew = true;
  bool _obscureConfirm = true;

  @override
  void dispose() {
    _currentCtrl.dispose();
    _newCtrl.dispose();
    _confirmCtrl.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await AuthRepository.instance.changePassword(
        _currentCtrl.text,
        _newCtrl.text,
      );
      if (!mounted) return;
      Navigator.of(context).pop();
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Пароль изменён')),
      );
    } on Object catch (e) {
      if (!mounted) return;
      setState(() => _error = apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return AlertDialog(
      backgroundColor: colors.bg2,
      title: Text('Смена пароля', style: TextStyle(color: colors.text)),
      content: SingleChildScrollView(
        child: Form(
          key: _formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                controller: _currentCtrl,
                obscureText: _obscureCurrent,
                decoration: InputDecoration(
                  labelText: 'Текущий пароль',
                  suffixIcon: IconButton(
                    icon: Icon(
                      _obscureCurrent ? Icons.visibility_off : Icons.visibility,
                      size: 18,
                    ),
                    onPressed: () =>
                        setState(() => _obscureCurrent = !_obscureCurrent),
                  ),
                ),
                validator: (v) =>
                    (v == null || v.isEmpty) ? 'Введите текущий пароль' : null,
              ),
              const SizedBox(height: 14),
              TextFormField(
                controller: _newCtrl,
                obscureText: _obscureNew,
                decoration: InputDecoration(
                  labelText: 'Новый пароль',
                  suffixIcon: IconButton(
                    icon: Icon(
                      _obscureNew ? Icons.visibility_off : Icons.visibility,
                      size: 18,
                    ),
                    onPressed: () =>
                        setState(() => _obscureNew = !_obscureNew),
                  ),
                ),
                validator: (v) {
                  if (v == null || v.length < 8) {
                    return 'Минимум 8 символов';
                  }
                  if (!v.contains(RegExp(r'[0-9]'))) {
                    return 'Нужна хотя бы одна цифра';
                  }
                  if (!v.contains(RegExp(r'[a-zA-Zа-яА-ЯёЁ]'))) {
                    return 'Нужна хотя бы одна буква';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 14),
              TextFormField(
                controller: _confirmCtrl,
                obscureText: _obscureConfirm,
                decoration: InputDecoration(
                  labelText: 'Повторите пароль',
                  suffixIcon: IconButton(
                    icon: Icon(
                      _obscureConfirm
                          ? Icons.visibility_off
                          : Icons.visibility,
                      size: 18,
                    ),
                    onPressed: () =>
                        setState(() => _obscureConfirm = !_obscureConfirm),
                  ),
                ),
                validator: (v) => v != _newCtrl.text
                    ? 'Пароли не совпадают'
                    : null,
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(
                  _error!,
                  style: TextStyle(color: colors.red, fontSize: 13),
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _busy ? null : () => Navigator.of(context).pop(),
          child: const Text('Отмена'),
        ),
        FilledButton(
          onPressed: _busy ? null : _save,
          child: _busy
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: Colors.white,
                  ),
                )
              : const Text('Сохранить'),
        ),
      ],
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// Диалог: реквизиты юрлица
// ═══════════════════════════════════════════════════════════════

class _RequisitesDialog extends StatefulWidget {
  const _RequisitesDialog({
    required this.userId,
    required this.cp,
    required this.onSaved,
  });

  final String userId;
  final Map<String, dynamic> cp;
  final VoidCallback onSaved;

  @override
  State<_RequisitesDialog> createState() => _RequisitesDialogState();
}

class _RequisitesDialogState extends State<_RequisitesDialog> {
  late final TextEditingController _company =
      TextEditingController(text: widget.cp['company_name'] as String? ?? '');
  late final TextEditingController _inn =
      TextEditingController(text: widget.cp['inn'] as String? ?? '');
  late final TextEditingController _kpp =
      TextEditingController(text: widget.cp['kpp'] as String? ?? '');
  late final TextEditingController _bik =
      TextEditingController(text: widget.cp['bik'] as String? ?? '');
  late final TextEditingController _legalAddr =
      TextEditingController(text: widget.cp['legal_address'] as String? ?? '');
  late final TextEditingController _bankAcc =
      TextEditingController(text: widget.cp['bank_account'] as String? ?? '');
  late final TextEditingController _corrAcc = TextEditingController(
    text: widget.cp['correspondent_account'] as String? ?? '',
  );
  late final TextEditingController _bankName =
      TextEditingController(text: widget.cp['bank_name'] as String? ?? '');
  late final TextEditingController _billingEmail =
      TextEditingController(text: widget.cp['billing_email'] as String? ?? '');
  late final TextEditingController _deliveryAddr =
      TextEditingController(text: widget.cp['delivery_address'] as String? ?? '');

  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _company.dispose();
    _inn.dispose();
    _kpp.dispose();
    _bik.dispose();
    _legalAddr.dispose();
    _bankAcc.dispose();
    _corrAcc.dispose();
    _bankName.dispose();
    _billingEmail.dispose();
    _deliveryAddr.dispose();
    super.dispose();
  }

  String? _orNull(TextEditingController c) {
    final v = c.text.trim();
    return v.isEmpty ? null : v;
  }

  Future<void> _save() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await AuthRepository.instance.updateClientProfile(widget.userId, {
        'company_name': _orNull(_company),
        'inn': _orNull(_inn),
        'kpp': _orNull(_kpp),
        'bik': _orNull(_bik),
        'legal_address': _orNull(_legalAddr),
        'bank_account': _orNull(_bankAcc),
        'correspondent_account': _orNull(_corrAcc),
        'bank_name': _orNull(_bankName),
        'billing_email': _orNull(_billingEmail),
        'delivery_address': _orNull(_deliveryAddr),
      });
      if (!mounted) return;
      Navigator.of(context).pop();
      widget.onSaved();
    } on Object catch (e) {
      if (!mounted) return;
      setState(() => _error = apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return AlertDialog(
      backgroundColor: colors.bg2,
      title:
          Text('Реквизиты организации', style: TextStyle(color: colors.text)),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            _field(_company, 'Наименование'),
            _field(_inn, 'ИНН', maxLength: 12, inputType: TextInputType.number),
            _field(_kpp, 'КПП', maxLength: 9, inputType: TextInputType.number),
            _field(_bik, 'БИК', maxLength: 9, inputType: TextInputType.number),
            _field(_legalAddr, 'Юридический адрес'),
            _field(_bankAcc, 'Расчётный счёт', maxLength: 20),
            _field(_corrAcc, 'Корреспондентский счёт', maxLength: 20),
            _field(_bankName, 'Банк'),
            _field(_billingEmail, 'Email для документов',
                inputType: TextInputType.emailAddress),
            _field(_deliveryAddr, 'Адрес доставки'),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(
                _error!,
                style: TextStyle(color: colors.red, fontSize: 13),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _busy ? null : () => Navigator.of(context).pop(),
          child: const Text('Отмена'),
        ),
        FilledButton(
          onPressed: _busy ? null : _save,
          child: _busy
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: Colors.white,
                  ),
                )
              : const Text('Сохранить'),
        ),
      ],
    );
  }

  Widget _field(
    TextEditingController ctrl,
    String label, {
    int? maxLength,
    TextInputType? inputType,
  }) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: TextFormField(
        controller: ctrl,
        maxLength: maxLength,
        keyboardType: inputType,
        decoration: InputDecoration(
          labelText: label,
          counterText: maxLength != null ? null : '',
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// Утилиты
// ═══════════════════════════════════════════════════════════════

String _roleLabel(String role) => switch (role) {
      'admin' => 'Администратор',
      'manager' => 'Менеджер',
      'driver' => 'Водитель',
      'client' => 'Клиент',
      _ => role,
    };
