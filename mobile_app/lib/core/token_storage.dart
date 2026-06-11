import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// JWT-пара в защищённом хранилище платформы (Keystore / Keychain).
class TokenStorage {
  TokenStorage._();
  static final TokenStorage instance = TokenStorage._();

  static const _kAccess = 'access_token';
  static const _kRefresh = 'refresh_token';

  final _storage = const FlutterSecureStorage();

  String? _accessCache;

  Future<String?> get accessToken async =>
      _accessCache ??= await _storage.read(key: _kAccess);

  Future<String?> get refreshToken => _storage.read(key: _kRefresh);

  Future<void> save({required String access, required String refresh}) async {
    _accessCache = access;
    await _storage.write(key: _kAccess, value: access);
    await _storage.write(key: _kRefresh, value: refresh);
  }

  Future<void> clear() async {
    _accessCache = null;
    await _storage.delete(key: _kAccess);
    await _storage.delete(key: _kRefresh);
  }

  Future<bool> get hasSession async => await refreshToken != null;
}
