import 'dart:developer' as developer;
import 'dart:io' show Platform;

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/app_config.dart';
import '../features/chat/chat_models.dart';
import '../features/chat/chat_repository.dart';
import '../features/chat/chat_screen.dart';

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

  /// NavigatorKey задаётся из main.dart для навигации из фона.
  GlobalKey<NavigatorState>? navigatorKey;

  /// Вызвать один раз на старте приложения, до registerCurrentToken().
  Future<void> init() async {
    try {
      await Firebase.initializeApp();
      _firebaseReady = true;
      FirebaseMessaging.instance.onTokenRefresh.listen((token) {
        _lastToken = token;
        _post(token);
      });

      // Пуш открыт когда приложение было на фоне/убито (tap on notification)
      FirebaseMessaging.onMessageOpenedApp.listen(_handlePushTap);

      // Пуш открыт когда приложение было полностью убито (initial message)
      final initial = await FirebaseMessaging.instance.getInitialMessage();
      if (initial != null) {
        // Откладываем навигацию до завершения первого фрейма
        WidgetsBinding.instance.addPostFrameCallback((_) {
          _handlePushTap(initial);
        });
      }
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

  /// FCM data payload для chat: type="chat_message", entity_type="conversation",
  /// entity_id=<conv_id>. Открываем ChatScreen для этого диалога.
  void _handlePushTap(RemoteMessage message) {
    final data = message.data;
    final type = data['type'] as String?;
    final entityType = data['entity_type'] as String?;
    final convId = data['entity_id'] as String?;

    if ((type == 'chat_message' || type == 'chat_new') &&
        entityType == 'conversation' &&
        convId != null &&
        convId.isNotEmpty) {
      _navigateToChat(convId);
    }
  }

  Future<void> _navigateToChat(String convId) async {
    final nav = navigatorKey?.currentState;
    if (nav == null) return;
    try {
      // Загрузить диалог, чтобы передать в ChatScreen
      final convs = await ChatRepository.instance.listConversations();
      Conversation? conv;
      for (final c in convs) {
        if (c.id == convId) { conv = c; break; }
      }
      if (conv == null) return;
      nav.push(MaterialPageRoute(
        builder: (_) => ChatScreen(conversation: conv!),
      ));
    } catch (e) {
      developer.log('PushRegistrar: не удалось открыть чат $convId: $e',
          name: 'push');
    }
  }
}
