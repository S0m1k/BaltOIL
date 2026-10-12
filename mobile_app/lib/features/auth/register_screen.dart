import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../home/home_screen.dart';
import 'auth_repository.dart';

/// Регистрация физического лица (веб doRegisterIndividual).
/// Поля зеркалят RegisterIndividualRequest бэка: телефон + пароль + ФИО
/// обязательны; email и адрес доставки — опциональны. После успеха бэк
/// сразу возвращает токены — уходим на главный экран.
class RegisterScreen extends StatefulWidget {
  const RegisterScreen({super.key});

  @override
  State<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends State<RegisterScreen> {
  final _formKey = GlobalKey<FormState>();
  final _fullName = TextEditingController();
  final _phone = TextEditingController();
  final _email = TextEditingController();
  final _address = TextEditingController();
  final _password = TextEditingController();
  final _password2 = TextEditingController();
  bool _busy = false;
  bool _obscure = true;
  String? _error;

  @override
  void dispose() {
    _fullName.dispose();
    _phone.dispose();
    _email.dispose();
    _address.dispose();
    _password.dispose();
    _password2.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await AuthRepository.instance.registerIndividual(
        phone: _phone.text.trim(),
        password: _password.text,
        fullName: _fullName.text.trim(),
        email: _email.text.trim(),
        deliveryAddress: _address.text.trim(),
      );
      if (!mounted) return;
      // Бэк уже залогинил — уходим на главный экран, стирая стек.
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => const HomeScreen()),
        (_) => false,
      );
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Регистрация успешна! Добро пожаловать.')),
      );
    } catch (e) {
      setState(() => _error = apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Регистрация')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextFormField(
                controller: _fullName,
                textCapitalization: TextCapitalization.words,
                decoration: const InputDecoration(
                  labelText: 'ФИО *',
                  hintText: 'Иванов Иван Иванович',
                  border: OutlineInputBorder(),
                ),
                validator: (v) => (v == null || v.trim().isEmpty)
                    ? 'Укажите ФИО'
                    : null,
              ),
              const SizedBox(height: 16),
              TextFormField(
                controller: _phone,
                keyboardType: TextInputType.phone,
                decoration: const InputDecoration(
                  labelText: 'Телефон *',
                  hintText: '+7 ...',
                  border: OutlineInputBorder(),
                ),
                validator: (v) {
                  final t = v?.trim() ?? '';
                  if (t.length < 4) return 'Укажите телефон';
                  return null;
                },
              ),
              const SizedBox(height: 16),
              TextFormField(
                controller: _email,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(
                  labelText: 'Email (необязательно)',
                  border: OutlineInputBorder(),
                ),
                validator: (v) {
                  final t = v?.trim() ?? '';
                  if (t.isEmpty) return null; // email опционален
                  if (!t.contains('@') || !t.contains('.')) {
                    return 'Некорректный email';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 16),
              TextFormField(
                controller: _address,
                textCapitalization: TextCapitalization.sentences,
                decoration: const InputDecoration(
                  labelText: 'Адрес доставки (необязательно)',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 16),
              TextFormField(
                controller: _password,
                obscureText: _obscure,
                decoration: InputDecoration(
                  labelText: 'Пароль *',
                  helperText: 'Минимум 6 символов',
                  border: const OutlineInputBorder(),
                  suffixIcon: IconButton(
                    icon: Icon(
                        _obscure ? Icons.visibility : Icons.visibility_off),
                    onPressed: () => setState(() => _obscure = !_obscure),
                  ),
                ),
                validator: (v) {
                  if ((v ?? '').length < 6) {
                    return 'Пароль не менее 6 символов';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 16),
              TextFormField(
                controller: _password2,
                obscureText: _obscure,
                decoration: const InputDecoration(
                  labelText: 'Повторите пароль *',
                  border: OutlineInputBorder(),
                ),
                onFieldSubmitted: (_) => _submit(),
                validator: (v) {
                  if (v != _password.text) return 'Пароли не совпадают';
                  return null;
                },
              ),
              if (_error != null) ...[
                const SizedBox(height: 16),
                Text(_error!, style: const TextStyle(color: Colors.red)),
              ],
              const SizedBox(height: 24),
              FilledButton(
                onPressed: _busy ? null : _submit,
                child: _busy
                    ? const SizedBox(
                        height: 20,
                        width: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Text('Зарегистрироваться'),
              ),
              const SizedBox(height: 8),
              Text(
                'Регистрация организации (юрлица) — через администратора.',
                textAlign: TextAlign.center,
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(color: Theme.of(context).colorScheme.outline),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
