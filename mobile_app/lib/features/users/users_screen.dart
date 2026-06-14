import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/api_client.dart';
import '../../core/theme.dart';
import '../auth/auth_repository.dart';
import 'users_repository.dart';

const Map<String, String> _kRoleLabels = {
  'admin': 'Администратор',
  'manager': 'Менеджер',
  'driver': 'Водитель',
  'client': 'Клиент',
};

const List<_RoleFilter> _kFilters = [
  _RoleFilter(label: 'Все', value: null),
  _RoleFilter(label: 'Менеджеры', value: 'manager'),
  _RoleFilter(label: 'Водители', value: 'driver'),
  _RoleFilter(label: 'Клиенты', value: 'client'),
  _RoleFilter(label: 'Админы', value: 'admin'),
];

class _RoleFilter {
  const _RoleFilter({required this.label, required this.value});

  final String label;
  final String? value;
}

class UsersScreen extends StatefulWidget {
  const UsersScreen({super.key, required this.user});

  final CurrentUser user;

  @override
  State<UsersScreen> createState() => _UsersScreenState();
}

class _UsersScreenState extends State<UsersScreen> {
  List<UserItem> _all = [];
  bool _loading = true;
  String? _error;
  String _query = '';
  String? _roleFilter; // null = all
  bool _showInactive = false;

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
      final items = await UsersRepository.instance.list(
        includeInactive: _showInactive,
        limit: 200,
      );
      if (!mounted) return;
      setState(() {
        _all = items;
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

  List<UserItem> get _filtered {
    var list = _all;

    if (_roleFilter != null) {
      list = list.where((u) => u.role == _roleFilter).toList();
    }

    final q = _query.toLowerCase().trim();
    if (q.isNotEmpty) {
      list = list.where((u) {
        return u.fullName.toLowerCase().contains(q) ||
            (u.email?.toLowerCase().contains(q) ?? false) ||
            (u.phone?.contains(q) ?? false) ||
            u.id.toLowerCase().contains(q);
      }).toList();
    }

    return list;
  }

  bool get _isAdmin => widget.user.role == 'admin';

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

    final filtered = _filtered;

    return Column(
      children: [
        // Search + create button row
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  onChanged: (v) => setState(() => _query = v),
                  decoration: InputDecoration(
                    hintText: 'Поиск пользователей…',
                    hintStyle: TextStyle(color: colors.text3),
                    prefixIcon:
                        Icon(Icons.search_rounded, color: colors.text3),
                    contentPadding: const EdgeInsets.symmetric(
                        horizontal: 12, vertical: 10),
                  ),
                ),
              ),
              if (_isAdmin) ...[
                const SizedBox(width: 8),
                FilledButton.icon(
                  onPressed: () => _showCreateDialog(context),
                  icon: const Icon(Icons.add_rounded, size: 18),
                  label: const Text('Создать'),
                  style: FilledButton.styleFrom(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 14, vertical: 10),
                  ),
                ),
              ],
            ],
          ),
        ),

        // Role filter chips
        SizedBox(
          height: 44,
          child: ListView.separated(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            scrollDirection: Axis.horizontal,
            itemCount: _kFilters.length,
            separatorBuilder: (_, _) => const SizedBox(width: 6),
            itemBuilder: (context, i) {
              final f = _kFilters[i];
              final selected = _roleFilter == f.value;
              return FilterChip(
                label: Text(f.label),
                selected: selected,
                onSelected: (_) {
                  setState(() => _roleFilter = f.value);
                },
                selectedColor: colors.primaryDim,
                checkmarkColor: colors.primary,
                labelStyle: TextStyle(
                  fontSize: 12,
                  color: selected ? colors.primary : colors.text2,
                  fontWeight:
                      selected ? FontWeight.w600 : FontWeight.w400,
                ),
                side: BorderSide(
                  color: selected ? colors.primary : colors.border,
                ),
                backgroundColor: colors.bg2,
                showCheckmark: false,
                visualDensity: VisualDensity.compact,
              );
            },
          ),
        ),

        // Show inactive toggle
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12),
          child: Row(
            children: [
              Text(
                'Показывать неактивных',
                style: TextStyle(fontSize: 13, color: colors.text2),
              ),
              const Spacer(),
              Switch(
                value: _showInactive,
                onChanged: (v) {
                  setState(() => _showInactive = v);
                  _load();
                },
                activeThumbColor: colors.primary,
              ),
            ],
          ),
        ),

        const SizedBox(height: 4),

        // List
        Expanded(
          child: RefreshIndicator(
            onRefresh: _load,
            color: colors.primary,
            child: filtered.isEmpty
                ? ListView(
                    children: [
                      SizedBox(
                          height:
                              MediaQuery.of(context).size.height * 0.2),
                      Center(
                        child: Text(
                          _query.isEmpty && _roleFilter == null
                              ? 'Нет пользователей'
                              : 'Ничего не найдено',
                          style: TextStyle(
                              color: colors.text3, fontSize: 15),
                        ),
                      ),
                    ],
                  )
                : ListView.separated(
                    padding: const EdgeInsets.fromLTRB(12, 0, 12, 24),
                    itemCount: filtered.length,
                    separatorBuilder: (_, _) => const SizedBox(height: 4),
                    itemBuilder: (context, i) => _UserRow(
                      user: filtered[i],
                      colors: colors,
                    ),
                  ),
          ),
        ),
      ],
    );
  }

  void _showCreateDialog(BuildContext context) {
    showDialog<void>(
      context: context,
      builder: (ctx) => _CreateUserDialog(
        onCreated: (_) {
          _load();
        },
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// User list row
// ---------------------------------------------------------------------------

class _UserRow extends StatelessWidget {
  const _UserRow({required this.user, required this.colors});

  final UserItem user;
  final AppColors colors;

  @override
  Widget build(BuildContext context) {
    final roleLabel =
        _kRoleLabels[user.role] ?? user.role;
    final roleColor = colors.roleColor(user.role);
    final shortId = user.id.length > 8
        ? '${user.id.substring(0, 8)}…'
        : user.id;

    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            // Status dot
            Container(
              width: 8,
              height: 8,
              margin: const EdgeInsets.only(right: 10),
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: user.isActive ? colors.accent : colors.text3,
              ),
            ),

            // Name + email
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    user.fullName,
                    style: TextStyle(
                      fontWeight: FontWeight.w600,
                      color: colors.text,
                      fontSize: 14,
                    ),
                  ),
                  if (user.email != null && user.email!.isNotEmpty) ...[
                    const SizedBox(height: 2),
                    Text(
                      user.email!,
                      style: TextStyle(fontSize: 12, color: colors.text2),
                    ),
                  ] else if (user.phone != null &&
                      user.phone!.isNotEmpty) ...[
                    const SizedBox(height: 2),
                    Text(
                      user.phone!,
                      style: TextStyle(fontSize: 12, color: colors.text2),
                    ),
                  ],
                ],
              ),
            ),

            // Role chip
            const SizedBox(width: 8),
            Container(
              padding:
                  const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
              decoration: BoxDecoration(
                color: roleColor.withAlpha(30),
                borderRadius: BorderRadius.circular(20),
              ),
              child: Text(
                roleLabel,
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                  color: roleColor,
                ),
              ),
            ),

            // UUID copy
            const SizedBox(width: 4),
            GestureDetector(
              onTap: () {
                Clipboard.setData(ClipboardData(text: user.id));
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text('UUID скопирован: $shortId'),
                    duration: const Duration(seconds: 2),
                  ),
                );
              },
              child: Padding(
                padding: const EdgeInsets.all(4),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      shortId,
                      style: TextStyle(
                        fontSize: 10,
                        color: colors.text3,
                        fontFamily: 'monospace',
                      ),
                    ),
                    const SizedBox(width: 3),
                    Icon(Icons.copy_rounded, size: 12, color: colors.text3),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Create user dialog (admin only)
// ---------------------------------------------------------------------------

class _CreateUserDialog extends StatefulWidget {
  const _CreateUserDialog({required this.onCreated});

  final void Function(UserItem) onCreated;

  @override
  State<_CreateUserDialog> createState() => _CreateUserDialogState();
}

class _CreateUserDialogState extends State<_CreateUserDialog> {
  final _formKey = GlobalKey<FormState>();
  final _nameCtrl = TextEditingController();
  final _emailCtrl = TextEditingController();
  final _phoneCtrl = TextEditingController();
  final _pwdCtrl = TextEditingController();

  String _role = 'manager';
  bool _saving = false;
  String? _saveError;

  static const List<String> _roles = ['manager', 'driver', 'client', 'admin'];

  @override
  void dispose() {
    _nameCtrl.dispose();
    _emailCtrl.dispose();
    _phoneCtrl.dispose();
    _pwdCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    final email = _emailCtrl.text.trim();
    final phone = _phoneCtrl.text.trim();
    if (email.isEmpty && phone.isEmpty) {
      setState(() => _saveError = 'Укажите телефон или email');
      return;
    }
    setState(() {
      _saving = true;
      _saveError = null;
    });
    try {
      final created = await UsersRepository.instance.createUser(
        CreateUserPayload(
          fullName: _nameCtrl.text.trim(),
          role: _role,
          password: _pwdCtrl.text,
          email: email.isEmpty ? null : email,
          phone: phone.isEmpty ? null : phone,
        ),
      );
      if (!mounted) return;
      Navigator.of(context).pop();
      widget.onCreated(created);
    } on Object catch (e) {
      if (!mounted) return;
      setState(() {
        _saveError = apiErrorMessage(e);
        _saving = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;

    return AlertDialog(
      backgroundColor: colors.bg2,
      title: Text(
        'Создать пользователя',
        style: TextStyle(color: colors.text, fontSize: 16),
      ),
      content: SizedBox(
        width: 360,
        child: Form(
          key: _formKey,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextFormField(
                  controller: _nameCtrl,
                  decoration: const InputDecoration(labelText: 'ФИО *'),
                  validator: (v) =>
                      (v == null || v.trim().isEmpty) ? 'Обязательное поле' : null,
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _emailCtrl,
                  decoration: const InputDecoration(labelText: 'Email'),
                  keyboardType: TextInputType.emailAddress,
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _phoneCtrl,
                  decoration: const InputDecoration(labelText: 'Телефон'),
                  keyboardType: TextInputType.phone,
                ),
                const SizedBox(height: 12),
                // Role dropdown
                DropdownButtonFormField<String>(
                  initialValue: _role,
                  decoration: InputDecoration(
                    labelText: 'Роль',
                    filled: true,
                    fillColor: colors.bg2,
                  ),
                  dropdownColor: colors.bg2,
                  items: _roles
                      .map(
                        (r) => DropdownMenuItem(
                          value: r,
                          child: Text(
                            _kRoleLabels[r] ?? r,
                            style: TextStyle(color: colors.text),
                          ),
                        ),
                      )
                      .toList(),
                  onChanged: (v) {
                    if (v != null) setState(() => _role = v);
                  },
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _pwdCtrl,
                  decoration: const InputDecoration(labelText: 'Пароль *'),
                  obscureText: true,
                  validator: (v) {
                    if (v == null || v.isEmpty) return 'Обязательное поле';
                    if (v.length < 8) return 'Минимум 8 символов';
                    if (!v.contains(RegExp(r'\d'))) {
                      return 'Нужна хотя бы одна цифра';
                    }
                    if (!v.contains(RegExp(r'[a-zA-Zа-яА-ЯёЁ]'))) {
                      return 'Нужна хотя бы одна буква';
                    }
                    return null;
                  },
                ),
                if (_saveError != null) ...[
                  const SizedBox(height: 10),
                  Text(
                    _saveError!,
                    style: TextStyle(color: colors.red, fontSize: 13),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _saving ? null : () => Navigator.of(context).pop(),
          child: Text('Отмена', style: TextStyle(color: colors.text2)),
        ),
        FilledButton(
          onPressed: _saving ? null : _submit,
          child: _saving
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(
                      strokeWidth: 2, color: Colors.white),
                )
              : const Text('Создать'),
        ),
      ],
    );
  }
}
