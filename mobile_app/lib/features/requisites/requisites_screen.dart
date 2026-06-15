import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/theme.dart';
import '../auth/auth_repository.dart';
import 'requisites_repository.dart';

/// Экран «Реквизиты» — реквизиты юридического лица продавца (БалтОйл).
///
/// Только для роли admin: загружает GET /admin/legal-entity, отображает
/// сгруппированную форму, при сохранении вызывает PUT /admin/legal-entity,
/// что создаёт новую версию и архивирует текущую.
///
/// Менеджеры и другие роли видят сообщение об ограниченном доступе.
class RequisitesScreen extends StatefulWidget {
  const RequisitesScreen({super.key, required this.user});

  final CurrentUser user;

  @override
  State<RequisitesScreen> createState() => _RequisitesScreenState();
}

class _RequisitesScreenState extends State<RequisitesScreen> {
  // ── Состояние загрузки ───────────────────────────────────────
  SellerLegalEntity? _entity;
  bool _loading = true;
  String? _loadError;

  // ── Форма ────────────────────────────────────────────────────
  final _formKey = GlobalKey<FormState>();

  // Юридическое лицо
  late final TextEditingController _name;
  late final TextEditingController _shortName;
  late final TextEditingController _inn;
  late final TextEditingController _kpp;
  late final TextEditingController _ogrn;
  late final TextEditingController _okpo;

  // Банковские реквизиты
  late final TextEditingController _bankName;
  late final TextEditingController _bik;
  late final TextEditingController _checkingAccount;
  late final TextEditingController _correspondentAccount;

  // Адреса и контакты
  late final TextEditingController _legalAddress;
  late final TextEditingController _actualAddress;
  late final TextEditingController _phone;
  late final TextEditingController _email;

  // Подписант
  late final TextEditingController _directorName;
  late final TextEditingController _directorTitle;

  // Налогообложение
  late final TextEditingController _vatRate;

  bool _saving = false;
  String? _saveError;
  bool _saveSuccess = false;

  bool get _isAdmin => widget.user.role == 'admin';

  @override
  void initState() {
    super.initState();
    _initControllers(null);
    if (_isAdmin) _load();
  }

  void _initControllers(SellerLegalEntity? e) {
    _name = TextEditingController(text: e?.name ?? '');
    _shortName = TextEditingController(text: e?.shortName ?? '');
    _inn = TextEditingController(text: e?.inn ?? '');
    _kpp = TextEditingController(text: e?.kpp ?? '');
    _ogrn = TextEditingController(text: e?.ogrn ?? '');
    _okpo = TextEditingController(text: e?.okpo ?? '');
    _bankName = TextEditingController(text: e?.bankName ?? '');
    _bik = TextEditingController(text: e?.bik ?? '');
    _checkingAccount = TextEditingController(text: e?.checkingAccount ?? '');
    _correspondentAccount =
        TextEditingController(text: e?.correspondentAccount ?? '');
    _legalAddress = TextEditingController(text: e?.legalAddress ?? '');
    _actualAddress = TextEditingController(text: e?.actualAddress ?? '');
    _phone = TextEditingController(text: e?.phone ?? '');
    _email = TextEditingController(text: e?.email ?? '');
    _directorName = TextEditingController(text: e?.directorName ?? '');
    _directorTitle =
        TextEditingController(text: e?.directorTitle ?? 'Директор');
    _vatRate = TextEditingController(
      text: e != null ? e.vatRate.toString() : '22',
    );
  }

  void _disposeControllers() {
    _name.dispose();
    _shortName.dispose();
    _inn.dispose();
    _kpp.dispose();
    _ogrn.dispose();
    _okpo.dispose();
    _bankName.dispose();
    _bik.dispose();
    _checkingAccount.dispose();
    _correspondentAccount.dispose();
    _legalAddress.dispose();
    _actualAddress.dispose();
    _phone.dispose();
    _email.dispose();
    _directorName.dispose();
    _directorTitle.dispose();
    _vatRate.dispose();
  }

  @override
  void dispose() {
    _disposeControllers();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _loadError = null;
      _saveSuccess = false;
    });
    try {
      final entity = await RequisitesRepository.instance.getCurrent();
      if (!mounted) return;
      _disposeControllers();
      _initControllers(entity);
      setState(() {
        _entity = entity;
        _loading = false;
      });
    } on Object catch (e) {
      if (!mounted) return;
      setState(() {
        _loadError = apiErrorMessage(e);
        _loading = false;
      });
    }
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() {
      _saving = true;
      _saveError = null;
      _saveSuccess = false;
    });

    String? orNull(TextEditingController c) {
      final v = c.text.trim();
      return v.isEmpty ? null : v;
    }

    final payload = <String, dynamic>{
      'name': _name.text.trim(),
      'short_name': orNull(_shortName),
      'inn': _inn.text.trim(),
      'kpp': orNull(_kpp),
      'ogrn': orNull(_ogrn),
      'okpo': orNull(_okpo),
      'bank_name': orNull(_bankName),
      'bik': orNull(_bik),
      'checking_account': orNull(_checkingAccount),
      'correspondent_account': orNull(_correspondentAccount),
      'legal_address': orNull(_legalAddress),
      'actual_address': orNull(_actualAddress),
      'phone': orNull(_phone),
      'email': orNull(_email),
      'director_name': orNull(_directorName),
      'director_title': orNull(_directorTitle),
      'vat_rate': int.tryParse(_vatRate.text.trim()) ?? 22,
    };

    try {
      final updated = await RequisitesRepository.instance.save(payload);
      if (!mounted) return;
      _disposeControllers();
      _initControllers(updated);
      setState(() {
        _entity = updated;
        _saving = false;
        _saveSuccess = true;
      });
    } on Object catch (e) {
      if (!mounted) return;
      setState(() {
        _saveError = apiErrorMessage(e);
        _saving = false;
      });
    }
  }

  // ── Build ────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;

    if (!_isAdmin) {
      return _AccessDeniedView(colors: colors);
    }

    if (_loading) {
      return Center(child: CircularProgressIndicator(color: colors.primary));
    }

    if (_loadError != null) {
      return _ErrorView(
        colors: colors,
        message: _loadError!,
        onRetry: _load,
      );
    }

    return RefreshIndicator(
      onRefresh: _load,
      color: colors.primary,
      child: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            // ── Шапка ─────────────────────────────────────────
            _ScreenHeader(
              colors: colors,
              hasEntity: _entity != null,
              effectiveFrom: _entity?.effectiveFrom,
            ),
            const SizedBox(height: 16),

            // ── 1. Юридическое лицо ───────────────────────────
            _SectionCard(
              colors: colors,
              title: 'ЮРИДИЧЕСКОЕ ЛИЦО',
              children: [
                _Field(
                  ctrl: _name,
                  label: 'Полное наименование *',
                  validator: (v) =>
                      (v == null || v.trim().isEmpty) ? 'Обязательное поле' : null,
                ),
                _Field(ctrl: _shortName, label: 'Краткое наименование'),
                _Field(
                  ctrl: _inn,
                  label: 'ИНН *',
                  hint: '10 или 12 цифр',
                  maxLength: 12,
                  inputType: TextInputType.number,
                  validator: (v) {
                    final s = v?.trim() ?? '';
                    if (s.isEmpty) return 'ИНН обязателен';
                    if (!RegExp(r'^\d{10}$|^\d{12}$').hasMatch(s)) {
                      return '10 цифр (юрлицо) или 12 (ИП)';
                    }
                    return null;
                  },
                ),
                _Field(
                  ctrl: _kpp,
                  label: 'КПП',
                  hint: '9 цифр',
                  maxLength: 9,
                  inputType: TextInputType.number,
                  validator: (v) {
                    final s = v?.trim() ?? '';
                    if (s.isNotEmpty && !RegExp(r'^\d{9}$').hasMatch(s)) {
                      return '9 цифр';
                    }
                    return null;
                  },
                ),
                _Field(
                  ctrl: _ogrn,
                  label: 'ОГРН',
                  hint: '13 или 15 цифр',
                  maxLength: 15,
                  inputType: TextInputType.number,
                ),
                _Field(
                  ctrl: _okpo,
                  label: 'ОКПО',
                  hint: '8 или 10 цифр',
                  maxLength: 10,
                  inputType: TextInputType.number,
                ),
              ],
            ),
            const SizedBox(height: 12),

            // ── 2. Банковские реквизиты ───────────────────────
            _SectionCard(
              colors: colors,
              title: 'БАНКОВСКИЕ РЕКВИЗИТЫ',
              children: [
                _Field(ctrl: _bankName, label: 'Наименование банка'),
                _Field(
                  ctrl: _bik,
                  label: 'БИК',
                  hint: '9 цифр',
                  maxLength: 9,
                  inputType: TextInputType.number,
                  validator: (v) {
                    final s = v?.trim() ?? '';
                    if (s.isNotEmpty && !RegExp(r'^\d{9}$').hasMatch(s)) {
                      return '9 цифр';
                    }
                    return null;
                  },
                ),
                _Field(
                  ctrl: _correspondentAccount,
                  label: 'Корр. счёт',
                  hint: '20 цифр',
                  maxLength: 20,
                  inputType: TextInputType.number,
                  validator: (v) {
                    final s = v?.trim() ?? '';
                    if (s.isNotEmpty && !RegExp(r'^\d{20}$').hasMatch(s)) {
                      return '20 цифр';
                    }
                    return null;
                  },
                ),
                _Field(
                  ctrl: _checkingAccount,
                  label: 'Расч. счёт',
                  hint: '20 цифр',
                  maxLength: 20,
                  inputType: TextInputType.number,
                  validator: (v) {
                    final s = v?.trim() ?? '';
                    if (s.isNotEmpty && !RegExp(r'^\d{20}$').hasMatch(s)) {
                      return '20 цифр';
                    }
                    return null;
                  },
                ),
              ],
            ),
            const SizedBox(height: 12),

            // ── 3. Адреса и контакты ─────────────────────────
            _SectionCard(
              colors: colors,
              title: 'АДРЕСА И КОНТАКТЫ',
              children: [
                _Field(ctrl: _legalAddress, label: 'Юридический адрес', maxLines: 2),
                _Field(ctrl: _actualAddress, label: 'Фактический адрес', maxLines: 2),
                _Field(
                  ctrl: _phone,
                  label: 'Телефон',
                  hint: '+7 900 000 00 00',
                  inputType: TextInputType.phone,
                ),
                _Field(
                  ctrl: _email,
                  label: 'Email',
                  hint: 'info@company.ru',
                  inputType: TextInputType.emailAddress,
                ),
              ],
            ),
            const SizedBox(height: 12),

            // ── 4. Подписант ──────────────────────────────────
            _SectionCard(
              colors: colors,
              title: 'ПОДПИСАНТ',
              children: [
                _Field(ctrl: _directorName, label: 'ФИО подписанта'),
                _Field(ctrl: _directorTitle, label: 'Должность', hint: 'Директор'),
              ],
            ),
            const SizedBox(height: 12),

            // ── 5. Налогообложение ────────────────────────────
            _SectionCard(
              colors: colors,
              title: 'НАЛОГООБЛОЖЕНИЕ',
              children: [
                _Field(
                  ctrl: _vatRate,
                  label: 'Ставка НДС, %',
                  hint: '22',
                  maxLength: 3,
                  inputType: TextInputType.number,
                  validator: (v) {
                    final n = int.tryParse(v?.trim() ?? '');
                    if (n == null || n < 0 || n > 100) {
                      return 'Число от 0 до 100';
                    }
                    return null;
                  },
                ),
              ],
            ),
            const SizedBox(height: 20),

            // ── Сообщение об успехе ───────────────────────────
            if (_saveSuccess)
              _Banner(
                color: colors.accent,
                icon: Icons.check_circle_outline_rounded,
                message: 'Реквизиты сохранены. Создана новая версия.',
                colors: colors,
              ),

            // ── Сообщение об ошибке ───────────────────────────
            if (_saveError != null)
              _Banner(
                color: colors.red,
                icon: Icons.error_outline_rounded,
                message: _saveError!,
                colors: colors,
              ),

            const SizedBox(height: 8),

            // ── Кнопка сохранения ─────────────────────────────
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: _saving ? null : _save,
                child: _saving
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      )
                    : Text(
                        _entity == null
                            ? 'Создать реквизиты'
                            : 'Сохранить новую версию',
                      ),
              ),
            ),
            const SizedBox(height: 32),
          ],
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// Вспомогательные виджеты
// ═══════════════════════════════════════════════════════════════

class _ScreenHeader extends StatelessWidget {
  const _ScreenHeader({
    required this.colors,
    required this.hasEntity,
    this.effectiveFrom,
  });

  final AppColors colors;
  final bool hasEntity;
  final DateTime? effectiveFrom;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(Icons.business_rounded, color: colors.primary, size: 22),
            const SizedBox(width: 8),
            Text(
              'Реквизиты продавца',
              style: TextStyle(
                color: colors.text,
                fontSize: 18,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
        const SizedBox(height: 4),
        Text(
          hasEntity
              ? 'Каждое сохранение создаёт новую версию реквизитов.'
                  '${effectiveFrom != null ? ' Текущая с ${_formatDate(effectiveFrom!)}.' : ''}'
              : 'Реквизиты ещё не созданы. Заполните форму и сохраните.',
          style: TextStyle(color: colors.text3, fontSize: 12),
        ),
      ],
    );
  }

  static String _formatDate(DateTime dt) {
    return '${dt.day.toString().padLeft(2, '0')}.${dt.month.toString().padLeft(2, '0')}.${dt.year}';
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
          Divider(height: 1, color: colors.border),
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 4),
            child: Column(children: children),
          ),
        ],
      ),
    );
  }
}

class _Field extends StatelessWidget {
  const _Field({
    required this.ctrl,
    required this.label,
    this.hint,
    this.maxLength,
    this.maxLines = 1,
    this.inputType,
    this.validator,
  });

  final TextEditingController ctrl;
  final String label;
  final String? hint;
  final int? maxLength;
  final int maxLines;
  final TextInputType? inputType;
  final String? Function(String?)? validator;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: TextFormField(
        controller: ctrl,
        maxLength: maxLength,
        maxLines: maxLines,
        keyboardType: inputType,
        validator: validator,
        decoration: InputDecoration(
          labelText: label,
          hintText: hint,
          // counterText='' скрывает счётчик maxLength, оставляем его
          // только если maxLength задан явно (пользователь должен видеть лимит).
          counterText: maxLength != null ? null : '',
        ),
      ),
    );
  }
}

class _Banner extends StatelessWidget {
  const _Banner({
    required this.color,
    required this.icon,
    required this.message,
    required this.colors,
  });

  final Color color;
  final IconData icon;
  final String message;
  final AppColors colors;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: color.withAlpha(25),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withAlpha(80)),
      ),
      child: Row(
        children: [
          Icon(icon, color: color, size: 18),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              message,
              style: TextStyle(color: color, fontSize: 13),
            ),
          ),
        ],
      ),
    );
  }
}

class _AccessDeniedView extends StatelessWidget {
  const _AccessDeniedView({required this.colors});

  final AppColors colors;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.lock_outline_rounded, size: 56, color: colors.text3),
            const SizedBox(height: 16),
            Text(
              'Раздел только для администратора',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: colors.text2,
                fontSize: 16,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              'Управление реквизитами юридического лица доступно'
              ' только администратору системы.',
              textAlign: TextAlign.center,
              style: TextStyle(color: colors.text3, fontSize: 13),
            ),
          ],
        ),
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({
    required this.colors,
    required this.message,
    required this.onRetry,
  });

  final AppColors colors;
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline_rounded, size: 48, color: colors.red),
            const SizedBox(height: 12),
            Text(
              message,
              textAlign: TextAlign.center,
              style: TextStyle(color: colors.text2),
            ),
            const SizedBox(height: 16),
            FilledButton(onPressed: onRetry, child: const Text('Повторить')),
          ],
        ),
      ),
    );
  }
}
