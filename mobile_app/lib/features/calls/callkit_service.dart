import 'dart:developer' as developer;

import 'package:flutter/material.dart';
import 'package:flutter_callkit_incoming/entities/entities.dart';
import 'package:flutter_callkit_incoming/flutter_callkit_incoming.dart';

import 'call_repository.dart';
import 'call_screen.dart';
import 'incoming_call_watcher.dart';

/// Нативный экран входящего звонка (Android ConnectionService / iOS CallKit).
///
/// Пуш `call_initiated` приходит data-only — фоновый FCM-обработчик показывает
/// системный экран звонка через [showIncoming]. Нажатия «Принять/Отклонить»
/// приходят в [FlutterCallkitIncoming.onEvent] и обрабатываются в [listen].
class CallkitService {
  CallkitService._();
  static final CallkitService instance = CallkitService._();

  GlobalKey<NavigatorState>? navigatorKey;
  bool _listening = false;

  /// Показать нативный экран входящего звонка. Данные — из пуша call_initiated.
  static Future<void> showIncoming({
    required String callId,
    required String roomName,
    required String callerName,
  }) async {
    final params = CallKitParams(
      id: callId,
      nameCaller: callerName,
      appName: 'СЗТК',
      handle: 'Входящий звонок',
      type: 0, // 0 — аудио, 1 — видео; камеру можно включить внутри звонка
      missedCallNotification: const NotificationParams(
        showNotification: true,
        isShowCallback: false,
        subtitle: 'Пропущенный звонок',
      ),
      duration: 45000, // авто-сброс через 45 с (как таймаут звонка на сервере)
      extra: {'call_id': callId, 'room_name': roomName},
      android: const AndroidParams(
        isCustomNotification: true,
        isShowLogo: false,
        ringtonePath: 'system_ringtone_default',
        backgroundColor: '#10151D',
        actionColor: '#0EA5E9',
        textAccept: 'Принять',
        textDecline: 'Отклонить',
        isShowFullLockedScreen: true, // экран поверх заблокированного
      ),
      ios: const IOSParams(handleType: 'generic', supportsVideo: true),
    );
    await FlutterCallkitIncoming.showCallkitIncoming(params);
  }

  /// Подписка на события callkit (accept/decline/timeout). Вызвать один раз
  /// на старте приложения из foreground.
  void listen() {
    if (_listening) return;
    _listening = true;
    FlutterCallkitIncoming.onEvent.listen((event) async {
      if (event == null) return;
      switch (event) {
        case CallEventActionCallAccept(:final callKitParams):
          final extra = callKitParams.extra ?? const {};
          await _onAccept(
            (extra['call_id'] ?? callKitParams.id)?.toString(),
            extra['room_name']?.toString(),
          );
          break;
        case CallEventActionCallDecline(:final callKitParams):
          final extra = callKitParams.extra ?? const {};
          await _onDecline((extra['call_id'] ?? callKitParams.id)?.toString());
          break;
        case CallEventActionCallTimeout():
          // Никто не поднял — система сама уберёт экран; на сервере звонок
          // завершится по таймауту.
          break;
        default:
          break;
      }
    });
  }

  Future<void> _onAccept(String? callId, String? roomName) async {
    if (callId == null) return;
    final nav = navigatorKey?.currentState;
    if (nav == null) return;
    try {
      // room_name из пуша может отсутствовать — добираем через API.
      final room = roomName ??
          (await CallRepository.instance.getCall(callId)).roomName;
      final token = await CallRepository.instance.token(room);
      await IncomingCallWatcher.instance.withInCall(() => nav.push(
            MaterialPageRoute(
              builder: (_) => CallScreen(token: token, remoteName: 'Звонок'),
            ),
          ));
    } on Object catch (e) {
      developer.log('CallKit accept failed: $e', name: 'callkit');
    } finally {
      await FlutterCallkitIncoming.endCall(callId);
    }
  }

  Future<void> _onDecline(String? callId) async {
    if (callId == null) return;
    try {
      await CallRepository.instance.end(callId);
    } on Object {
      // Сервер недоступен — звонок истечёт по таймауту.
    }
  }

  /// Снять все активные экраны звонка (например, при выходе или отбое).
  static Future<void> endAll() => FlutterCallkitIncoming.endAllCalls();
}
