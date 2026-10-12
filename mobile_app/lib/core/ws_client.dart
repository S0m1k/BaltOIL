import 'dart:async';
import 'dart:convert';
import 'dart:developer' as developer;
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/io.dart';

import 'app_config.dart';
import 'token_storage.dart';
import 'api_client.dart';

/// Перечень специальных кодов закрытия WS, которые выставляет chat_service.
const _kCodeTokenExpired = 4401;
const _kCodeRateLimit = 4029;
const _kCodeBadAuth = 4001;
const _kCodeNotFound = 4004;
const _kCodeForbidden = 4003;

/// Входящее сообщение из WebSocket-канала.
///
/// Если поле [error] != null — это сервисная ошибка, [message] равен null.
class WsFrame {
  const WsFrame({this.message, this.error});

  final Map<String, dynamic>? message;
  final String? error;

  bool get isError => error != null;
}

/// Клиент WebSocket для одного чата (conv_id).
///
/// Жизненный цикл:
///   1. Создать, передать conv_id.
///   2. Подписаться на [frames].
///   3. Вызвать [connect] — клиент авторизуется первым фреймом.
///   4. [send] — отправить текст (чистая строка, не JSON).
///   5. [dispose] — закрыть соединение при уходе с экрана.
///
/// Автоматический реконнект:
///   - 4401 (token expired): обновляем токен через ApiClient и переподключаемся.
///   - 4001/4003/4004: не реконнектимся (ошибка конфигурации/доступа).
///   - 4029 (rate limit): backoff 5 секунд.
///   - Прочие закрытия (сеть, таймаут): backoff-реконнект.
class ChatWsClient {
  ChatWsClient({required this.convId});

  final String convId;

  final _controller = StreamController<WsFrame>.broadcast();

  Stream<WsFrame> get frames => _controller.stream;

  IOWebSocketChannel? _channel;
  StreamSubscription<dynamic>? _sub;
  bool _disposed = false;
  int _backoffSeconds = 1;

  // Called externally (from WidgetsBindingObserver) when app resumes foreground.
  void onAppResume() {
    if (!_disposed && (_channel == null)) {
      connect();
    }
  }

  Future<void> connect() async {
    if (_disposed) return;
    await _sub?.cancel();
    _sub = null;
    _channel = null;

    final token = await TokenStorage.instance.accessToken;
    if (token == null) return;

    final uri = Uri.parse('${AppConfig.wsBase}/ws/$convId');

    try {
      // Для локальной разработки с самоподписанным сертификатом (mirror Dio behaviour).
      HttpClient? httpClient;
      if (AppConfig.allowBadCertificates && !kReleaseMode) {
        httpClient = HttpClient()
          ..badCertificateCallback = (cert, host, port) => true;
      }
      final channel = IOWebSocketChannel.connect(uri, customClient: httpClient);
      _channel = channel;

      // Первый фрейм — авторизация токеном
      channel.sink.add(jsonEncode({'token': token}));

      _sub = channel.stream.listen(_onData, onError: _onError, onDone: _onDone);
    } catch (e) {
      // Synchronous setup errors (e.g. URI parse failure) — schedule reconnect.
      developer.log('ChatWsClient: connect error: $e', name: 'ws');
      _scheduleReconnect();
    }
  }

  /// Отправить текстовое сообщение (raw string, не JSON — таков протокол).
  void send(String text) {
    _channel?.sink.add(text);
  }

  /// Ответ на сообщение: сервер принимает JSON {"text","reply_to_id"}
  /// (chat_service websocket.py, правки 2026-06-24).
  void sendReply(String text, String replyToId) {
    _channel?.sink.add(jsonEncode({'text': text, 'reply_to_id': replyToId}));
  }

  void _onData(dynamic raw) {
    if (raw is! String) return;
    // Successful data received — the channel is healthy; reset backoff.
    _backoffSeconds = 1;
    try {
      final json = jsonDecode(raw) as Map<String, dynamic>;
      if (json.containsKey('error')) {
        final err = json['error'] as String;
        _controller.add(WsFrame(error: err));
        // 4401 handled via onDone (server closes after sending the error frame)
      } else {
        _controller.add(WsFrame(message: json));
      }
    } catch (_) {
      // malformed frame — ignore
    }
  }

  void _onError(Object error) {
    // Network-level errors — onDone will also fire after this,
    // so reconnect logic lives in _onDone to avoid double-scheduling.
    developer.log('ChatWsClient: stream error: $error', name: 'ws');
  }

  // ignore: avoid_void_async  — onDone callback must be void; errors are logged.
  void _onDone() async {
    if (_disposed) return;
    final code = _channel?.closeCode;
    _channel = null;
    _sub = null;

    developer.log('ChatWsClient: closed code=$code', name: 'ws');

    try {
      switch (code) {
        case _kCodeTokenExpired:
          // Refresh token and reconnect immediately
          final refreshed = await ApiClient.instance.refreshTokenPublic();
          if (refreshed && !_disposed) {
            await connect();
          }
          return;
        case _kCodeBadAuth:
        case _kCodeForbidden:
        case _kCodeNotFound:
          // Permanent errors — do not reconnect
          return;
        case _kCodeRateLimit:
          // Back off longer on rate limit
          await Future.delayed(const Duration(seconds: 5));
          if (!_disposed) await connect();
          return;
        default:
          _scheduleReconnect();
      }
    } catch (e) {
      developer.log('ChatWsClient: _onDone error: $e', name: 'ws');
      _scheduleReconnect();
    }
  }

  void _scheduleReconnect() {
    if (_disposed) return;
    final delay = _backoffSeconds;
    _backoffSeconds = (_backoffSeconds * 2).clamp(1, 30);
    Future.delayed(Duration(seconds: delay), () {
      if (!_disposed) connect();
    });
  }

  void dispose() {
    _disposed = true;
    _sub?.cancel();
    _channel?.sink.close();
    _controller.close();
  }
}
