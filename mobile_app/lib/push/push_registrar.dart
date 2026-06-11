import 'dart:developer' as developer;
import 'dart:io' show Platform;

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';

import '../core/api_client.dart';
import '../core/app_config.dart';

/// Регистрация FCM-токена устройства на бэке (POST /api/v1/devices).
///
/// Работает только когда проект сконфигурирован под Firebase
/// (google-services.json / GoogleService-Info.plist). Без него
/// Firebase.initializeApp() бросает — ловим и тихо отключаем пуши,
/// приложение продолжает работать (уведомления видны на экране «Уведомления»).
class PushRegistrar {
  PushRegistrar._();
  static final PushRegistrar instance = PushRegistrar._();

  bool _firebaseReady = false;
  String? _lastToken;

  /// Вызвать один раз на старте приложения, до registerCurrentToken().
  Future<void> init() async {
    try {
      await Firebase.initializeApp();
      _firebaseReady = true;
      FirebaseMessaging.instance.onTokenRefresh.listen((token) {
        _lastToken = token;
        _post(token);
      });
    } catch (e) {
      developer.log('Firebase не сконфигурирован — пуши отключены: $e',
          name: 'push');
    }
  }

  Future<void> registerCurrentToken() async {
    if (!_firebaseReady) return;
    try {
      await FirebaseMessaging.instance.requestPermission();
      final token = await FirebaseMessaging.instance.getToken();
      if (token == null) return;
      _lastToken = token;
      await _post(token);
    } catch (e) {
      developer.log('Не удалось зарегистрировать FCM-токен: $e', name: 'push');
    }
  }

  Future<void> unregisterCurrentToken() async {
    if (!_firebaseReady || _lastToken == null) return;
    try {
      await ApiClient.instance.dio
          .delete('${AppConfig.notificationBase}/devices/$_lastToken');
    } catch (e) {
      developer.log('Не удалось удалить FCM-токен: $e', name: 'push');
    }
  }

  Future<void> _post(String token) async {
    await ApiClient.instance.dio.post(
      '${AppConfig.notificationBase}/devices',
      data: {'platform': Platform.isIOS ? 'ios' : 'android', 'token': token},
    );
  }
}
