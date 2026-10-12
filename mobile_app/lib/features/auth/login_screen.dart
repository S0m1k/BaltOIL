import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../home/home_screen.dart';
import 'auth_repository.dart';
import 'register_screen.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  @override
  Widget build(BuildContext context) {
    // Вход по SMS скрыт как на вебе (d89ff92) — только пароль, без вкладок.
    // _SmsLoginTab сохранён в файле: чтобы вернуть, снова обернуть в
    // DefaultTabController(length: 2) + TabBar/TabBarView.
    return Scaffold(
      appBar: AppBar(
        // Логотип как на вебе: СЗТК градиентом голубой→зелёный.
        title: ShaderMask(
          shaderCallback: (bounds) => const LinearGradient(
            colors: [Color(0xFF0EA5E9), Color(0xFF10B981)],
          ).createShader(bounds),
          child: const Text(
            'СЗТК',
            style: TextStyle(
              color: Colors.white,
              fontWeight: FontWeight.w700,
              letterSpacing: 3,
            ),
          ),
        ),
      ),
      body: const _PasswordLoginTab(),
    );
  }
}

void _goHome(BuildContext context) {
  Navigator.of(context).pushAndRemoveUntil(
    MaterialPageRoute(builder: (_) => const HomeScreen()),
    (_) => false,
  );
}

class _PasswordLoginTab extends StatefulWidget {
  const _PasswordLoginTab();

  @override
  State<_PasswordLoginTab> createState() => _PasswordLoginTabState();
}

class _PasswordLoginTabState extends State<_PasswordLoginTab> {
  final _login = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;
  String? _error;

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await AuthRepository.instance
          .loginWithPassword(_login.text.trim(), _password.text);
      if (mounted) _goHome(context);
    } catch (e) {
      setState(() => _error = apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        children: [
          TextField(
            controller: _login,
            keyboardType: TextInputType.emailAddress,
            decoration: const InputDecoration(
              labelText: 'Телефон или email',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _password,
            obscureText: true,
            decoration: const InputDecoration(
              labelText: 'Пароль',
              border: OutlineInputBorder(),
            ),
            onSubmitted: (_) => _submit(),
          ),
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(_error!, style: const TextStyle(color: Colors.red)),
          ],
          const SizedBox(height: 24),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: _busy ? null : _submit,
              child: _busy
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(strokeWidth: 2))
                  : const Text('Войти'),
            ),
          ),
          const SizedBox(height: 8),
          // Регистрация физлица (веб switchAuthMode('register')). Юрлицо
          // заводит администратор, поэтому здесь только физлицо.
          TextButton(
            onPressed: _busy
                ? null
                : () => Navigator.of(context).push(MaterialPageRoute(
                      builder: (_) => const RegisterScreen(),
                    )),
            child: const Text('Нет аккаунта? Зарегистрироваться'),
          ),
        ],
      ),
    );
  }
}

class _SmsLoginTab extends StatefulWidget {
  const _SmsLoginTab();

  @override
  State<_SmsLoginTab> createState() => _SmsLoginTabState();
}

class _SmsLoginTabState extends State<_SmsLoginTab> {
  final _phone = TextEditingController();
  final _code = TextEditingController();
  bool _busy = false;
  bool _codeSent = false;
  String? _error;

  Future<void> _requestCode() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await AuthRepository.instance.requestSmsCode(_phone.text.trim());
      setState(() => _codeSent = true);
    } catch (e) {
      setState(() => _error = apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _verify() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await AuthRepository.instance
          .verifySmsCode(_phone.text.trim(), _code.text.trim());
      if (mounted) _goHome(context);
    } catch (e) {
      setState(() => _error = apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        children: [
          TextField(
            controller: _phone,
            keyboardType: TextInputType.phone,
            enabled: !_codeSent,
            decoration: const InputDecoration(
              labelText: 'Телефон',
              hintText: '+7 ...',
              border: OutlineInputBorder(),
            ),
          ),
          if (_codeSent) ...[
            const SizedBox(height: 16),
            TextField(
              controller: _code,
              keyboardType: TextInputType.number,
              maxLength: 6,
              decoration: const InputDecoration(
                labelText: 'Код из SMS',
                border: OutlineInputBorder(),
                counterText: '',
              ),
              onSubmitted: (_) => _verify(),
            ),
          ],
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(_error!, style: const TextStyle(color: Colors.red)),
          ],
          const SizedBox(height: 24),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: _busy ? null : (_codeSent ? _verify : _requestCode),
              child: _busy
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(strokeWidth: 2))
                  : Text(_codeSent ? 'Войти' : 'Получить код'),
            ),
          ),
          if (_codeSent)
            TextButton(
              onPressed: _busy
                  ? null
                  : () => setState(() {
                        _codeSent = false;
                        _code.clear();
                      }),
              child: const Text('Изменить номер'),
            ),
        ],
      ),
    );
  }
}
