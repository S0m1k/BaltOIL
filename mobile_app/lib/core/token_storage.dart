import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// JWT-пара в защищённом хранилище платформы (Keystore / Keychain).
class TokenStorage {
  TokenStorage._();
  static final TokenStorage instance = TokenStorage._();

  static const _kAccess = 'access_token';
  static const _kRefresh = 'refresh_token';

  final _storage = const FlutterSecureStorage();

  String? _accessCache;

  /// Номер сессии: растёт при каждом входе и при каждом выходе.
  ///
  /// Нужен, чтобы отличить 401 от запроса ПРОШЛОЙ сессии (он висел в полёте,
  /// пока пользователь заново логинился) от 401 текущей: первый не повод
  /// рвать свежую сессию, иначе вход заканчивается мгновенным выкидыванием
  /// на экран входа.
  int get generation => _generation;
  int _generation = 0;

  Future<String?> get accessToken async =>
      _accessCache ??= await _storage.read(key: _kAccess);

  Future<String?> get refreshToken => _storage.read(key: _kRefresh);

  /// [newSession] — это вход (логин/регистрация/SMS), а не ротация пары при
  /// refresh: только вход начинает новую сессию и двигает [generation].
  Future<void> save({
    required String access,
    required String refresh,
    bool newSession = false,
  }) async {
    if (newSession) _generation++;
    _accessCache = access;
    await _storage.write(key: _kAccess, value: access);
    await _storage.write(key: _kRefresh, value: refresh);
  }

  Future<void> clear() async {
    _generation++;
    _accessCache = null;
    await _storage.delete(key: _kAccess);
    await _storage.delete(key: _kRefresh);
  }

  Future<bool> get hasSession async => await refreshToken != null;
}
