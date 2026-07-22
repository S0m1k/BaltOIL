import 'dart:developer' as developer;
import 'dart:io' show Platform;

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/app_config.dart';
import '../features/calls/callkit_service.dart';
import '../features/calls/incoming_call_watcher.dart';
import '../features/chat/chat_models.dart';
import '../features/chat/chat_repository.dart';
import '../features/chat/chat_screen.dart';

/// Фоновый обработчик FCM (top-level, отдельный изолят). Для data-only пуша
/// call_initiated показывает нативный экран входящего звонка — работает даже
/// когда приложение убито. Должен быть top-level с vm:entry-point.
@pragma('vm:entry-point')
Future<void> firebaseBackgroundHandler(RemoteMessage message) async {
  if (message.data['type'] != 'call_initiated') return;
  final callId = message.data['entity_id'] ?? message.data['call_id'];
  if (callId == null || (callId as String).isEmpty) return;
  await CallkitService.showIncoming(
    callId: callId,
    roomName: (message.data['room_name'] ?? '') as String,
    callerName: (message.data['initiated_by_name'] ??
        message.data['title'] ??
        'Входящий звонок') as String,
  );
}

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

      // Фоновый обработчик (звонки при свёрнутом/убитом приложении).
      FirebaseMessaging.onBackgroundMessage(firebaseBackgroundHandler);

      FirebaseMessaging.instance.onTokenRefresh.listen((token) {
        _lastToken = token;
        _post(token);
      });

      // Пуш открыт когда приложение было на фоне/убито (tap on notification)
      FirebaseMessaging.onMessageOpenedApp.listen(_handlePushTap);

      // Пуш пришёл при открытом приложении: показываем СВОЙ полноэкранный
      // входящий с зацикленным рингтоном (правки 2026-07-22). Callkit-шторку
      // в форграунде MIUI глушила после одного-двух гудков; callkit остаётся
      // только для фона/убитого приложения (onBackgroundMessage).
      FirebaseMessaging.onMessage.listen((message) {
        if (message.data['type'] == 'call_initiated') {
          final callId =
              (message.data['entity_id'] ?? message.data['call_id']) as String?;
          if (callId != null && callId.isNotEmpty) {
            // ignore: discarded_futures
            IncomingCallWatcher.instance.openFromPush(callId);
          }
        }
      });

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

    // Входящий звонок (2026-07-17): в data только call_id (entity_id) —
    // room_name и статус добираются через GET /calls/{id}.
    if (type == 'call_initiated' &&
        entityType == 'call' &&
        convId != null &&
        convId.isNotEmpty) {
      IncomingCallWatcher.instance.openFromPush(convId);
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
