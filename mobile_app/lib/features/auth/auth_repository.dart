import 'package:dio/dio.dart';

import '../../core/api_client.dart';
import '../../core/app_config.dart';
import '../../core/token_storage.dart';
import '../../push/push_registrar.dart';

class CurrentUser {
  CurrentUser({
    required this.id,
    required this.role,
    required this.fullName,
    this.chatsOnly = false,
  });

  final String id;
  final String role; // client | driver | manager | admin
  final String fullName;

  /// Режим «только чаты» (правки 2026-07-14): клиент видит в системе
  /// только мессенджер (+профиль), создание заявок запрещено.
  final bool chatsOnly;

  factory CurrentUser.fromJson(Map<String, dynamic> json) => CurrentUser(
        id: json['id'] as String,
        role: json['role'] as String,
        fullName: (json['full_name'] ?? '') as String,
        chatsOnly: ((json['client_profile']
                as Map<String, dynamic>?)?['chats_only'] ??
            false) as bool,
      );
}

/// Краткая карточка пользователя для выпадающих списков (клиенты/водители).
class UserBrief {
  UserBrief({required this.id, required this.fullName, this.phone});

  final String id;
  final String fullName;
  final String? phone;

  factory UserBrief.fromJson(Map<String, dynamic> json) => UserBrief(
        id: json['id'] as String,
        fullName: (json['full_name'] ?? '') as String,
        phone: json['phone'] as String?,
      );

  /// Метка для дропдауна: имя + телефон, если есть.
  String get label =>
      phone != null && phone!.isNotEmpty ? '$fullName · $phone' : fullName;
}

class AuthRepository {
  AuthRepository._();
  static final AuthRepository instance = AuthRepository._();

  Dio get _dio => ApiClient.instance.dio;
  String get _base => AppConfig.authBase;

  /// Разовый клиент из формы заявки (веб __oneoff__, правки 2026-07-11):
  /// создаёт физика без email/пароля или находит существующего по телефону.
  /// Возвращает {id, full_name, is_one_off, ...} (UserShortResponse).
  Future<Map<String, dynamic>> createOneOffClient({
    required String fullName,
    required String phone,
  }) async {
    final resp = await _dio.post(
      '$_base/users/one-off',
      data: {'full_name': fullName, 'phone': phone},
    );
    return resp.data as Map<String, dynamic>;
  }

  /// Список пользователей по роли (client/driver/...) — для форм менеджера.
  Future<List<UserBrief>> listByRole(String role) async {
    final resp = await _dio.get('$_base/users', queryParameters: {'role': role});
    final data = resp.data as List<dynamic>;
    return data
        .map((e) => UserBrief.fromJson(e as Map<String, dynamic>))
        .toList();
  }

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

  /// Регистрация физлица (веб doRegisterIndividual, /auth/register/individual).
  /// Бэк после создания сразу логинит — возвращает токены. Юрлица заводит
  /// администратор, поэтому в приложении регистрируем только физлиц.
  Future<void> registerIndividual({
    required String phone,
    required String password,
    required String fullName,
    String? email,
    String? deliveryAddress,
  }) async {
    final resp = await _dio.post(
      '$_base/auth/register/individual',
      data: {
        'phone': phone,
        'password': password,
        'full_name': fullName,
        if (email != null && email.isNotEmpty) 'email': email,
        if (deliveryAddress != null && deliveryAddress.isNotEmpty)
          'delivery_address': deliveryAddress,
      },
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

  /// Полный профиль текущего пользователя (включает client_profile).
  Future<Map<String, dynamic>> meFullProfile() async {
    final resp = await _dio.get('$_base/auth/me');
    return resp.data as Map<String, dynamic>;
  }

  /// Обновить собственные данные (full_name, email, phone).
  /// Все поля опциональны — передаём только изменённые.
  Future<Map<String, dynamic>> updateMe(
    String userId,
    Map<String, dynamic> fields,
  ) async {
    final resp = await _dio.patch('$_base/users/$userId', data: fields);
    return resp.data as Map<String, dynamic>;
  }

  /// Обновить client_profile (адрес доставки, реквизиты юрлица и т.д.).
  Future<void> updateClientProfile(
    String userId,
    Map<String, dynamic> fields,
  ) async {
    await _dio.patch('$_base/users/$userId/profile', data: fields);
  }

  /// Смена пароля (все роли). Требует текущий пароль.
  Future<void> changePassword(
    String currentPassword,
    String newPassword,
  ) async {
    await _dio.post(
      '$_base/users/me/change-password',
      data: {
        'current_password': currentPassword,
        'new_password': newPassword,
      },
    );
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
