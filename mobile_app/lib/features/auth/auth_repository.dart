import 'package:dio/dio.dart';

import '../../core/api_client.dart';
import '../../core/app_config.dart';
import '../../core/token_storage.dart';
import '../../push/push_registrar.dart';

class CurrentUser {
  CurrentUser({required this.id, required this.role, required this.fullName});

  final String id;
  final String role; // client | driver | manager | admin
  final String fullName;

  factory CurrentUser.fromJson(Map<String, dynamic> json) => CurrentUser(
        id: json['id'] as String,
        role: json['role'] as String,
        fullName: (json['full_name'] ?? '') as String,
      );
}

class AuthRepository {
  AuthRepository._();
  static final AuthRepository instance = AuthRepository._();

  Dio get _dio => ApiClient.instance.dio;
  String get _base => AppConfig.authBase;

  Future<void> _saveTokens(Map<String, dynamic> data) async {
    await TokenStorage.instance.save(
      access: data['access_token'] as String,
      refresh: data['refresh_token'] as String,
    );
    // Привязываем устройство к новому пользователю (no-op без Firebase).
    await PushRegistrar.instance.registerCurrentToken();
  }

  /// Вход по телефону/email + паролю.
  Future<void> loginWithPassword(String login, String password) async {
    final resp = await _dio.post(
      '$_base/auth/login',
      data: {'login': login, 'password': password},
      options: Options(extra: {'noAuth': true}),
    );
    await _saveTokens(resp.data as Map<String, dynamic>);
  }

  /// Шаг 1 входа по SMS: запросить код.
  Future<void> requestSmsCode(String phone) async {
    await _dio.post(
      '$_base/auth/login/request-code',
      data: {'phone': phone},
      options: Options(extra: {'noAuth': true}),
    );
  }

  /// Шаг 2 входа по SMS: проверить код, получить токены.
  Future<void> verifySmsCode(String phone, String code) async {
    final resp = await _dio.post(
      '$_base/auth/login/verify-code',
      data: {'phone': phone, 'code': code},
      options: Options(extra: {'noAuth': true}),
    );
    await _saveTokens(resp.data as Map<String, dynamic>);
  }

  Future<CurrentUser> me() async {
    final resp = await _dio.get('$_base/auth/me');
    return CurrentUser.fromJson(resp.data as Map<String, dynamic>);
  }

  Future<void> logout() async {
    await PushRegistrar.instance.unregisterCurrentToken();
    final refresh = await TokenStorage.instance.refreshToken;
    if (refresh != null) {
      try {
        await _dio.post('$_base/auth/logout', data: {'refresh_token': refresh});
      } catch (_) {
        // Сервер недоступен — локальный выход всё равно выполняем.
      }
    }
    await TokenStorage.instance.clear();
  }
}
