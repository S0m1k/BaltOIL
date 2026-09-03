// Регрессия на «выкидывает из аккаунта» (правки 2026-09-03).
//
// Главный сценарий: пока пользователь вводит логин, фоновые опросы (поллинг
// звонков раз в 4 с, outbox, WS) продолжают стучаться с мёртвым токеном. Их
// 401 прилетал уже ПОСЛЕ успешного входа и сносил свежую сессию. Проверяем,
// что теперь такой «хвост» новую сессию не трогает, а настоящий отказ
// refresh-токена по-прежнему выводит на экран входа.
//
// Запуск из папки mobile_app:  flutter test test/auth_session_test.dart
import 'dart:async';
import 'dart:convert';

import 'package:baltoil_mobile/core/api_client.dart';
import 'package:baltoil_mobile/core/token_storage.dart';
import 'package:dio/dio.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

// Ответ адаптера: код + тело.
typedef _Reply = ({int code, Map<String, dynamic> body});

// Подменяет транспорт Dio: вместо сети — заданная функция.
class _FakeAdapter implements HttpClientAdapter {
  _FakeAdapter(this.onFetch);

  final Future<_Reply> Function(RequestOptions options) onFetch;

  @override
  void close({bool force = false}) {}

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    final reply = await onFetch(options);
    return ResponseBody.fromString(
      jsonEncode(reply.body),
      reply.code,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }
}

// In-memory замена Keychain/Keystore: flutter_secure_storage в тестах
// не имеет нативной части, поэтому перехватываем её канал.
void _installFakeSecureStorage() {
  const channel = MethodChannel('plugins.it_nomads.com/flutter_secure_storage');
  final store = <String, String>{};
  TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
      .setMockMethodCallHandler(channel, (call) async {
    final args = (call.arguments as Map?)?.cast<String, dynamic>() ?? {};
    switch (call.method) {
      case 'read':
        return store[args['key'] as String];
      case 'write':
        store[args['key'] as String] = args['value'] as String;
        return null;
      case 'delete':
        store.remove(args['key'] as String);
        return null;
      case 'readAll':
        return Map<String, String>.from(store);
      case 'deleteAll':
        store.clear();
        return null;
      case 'containsKey':
        return store.containsKey(args['key'] as String);
      default:
        return null;
    }
  });
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late List<String> calls; // пути запросов, дошедших до транспорта
  late int expiredCount; // сколько раз позвали onSessionExpired

  setUp(() {
    _installFakeSecureStorage();
    calls = [];
    expiredCount = 0;
    ApiClient.instance.onSessionExpired = () => expiredCount++;
  });

  tearDown(() => ApiClient.instance.onSessionExpired = null);

  String? bearerOf(RequestOptions o) =>
      (o.headers['Authorization'] as String?)?.replaceFirst('Bearer ', '');

  test('401 от запроса прошлой сессии не выкидывает из нового аккаунта',
      () async {
    await TokenStorage.instance
        .save(access: 'A-old', refresh: 'R-old', newSession: true);

    // Запрос «зависает» в сети до тех пор, пока не произойдёт новый вход —
    // ровно как поллинг звонков, стартовавший до ввода логина.
    // reachedNetwork нужен для строгого порядка: без него onRequest (он async)
    // успевал подставить УЖЕ новый токен, и гонка не воспроизводилась.
    final reachedNetwork = Completer<void>();
    final loggedInAgain = Completer<void>();
    ApiClient.instance.dio.httpClientAdapter = _FakeAdapter((o) async {
      calls.add('${o.path}#${bearerOf(o)}');
      if (o.path.endsWith('/slow') && bearerOf(o) == 'A-old') {
        if (!reachedNetwork.isCompleted) reachedNetwork.complete();
        await loggedInAgain.future;
        // Токен старой сессии сервер уже не принимает.
        return (code: 401, body: {'detail': 'x'});
      }
      return (code: 200, body: {'ok': true});
    });

    final inFlight = ApiClient.instance.dio.get('https://x.test/slow');
    // Ждём, пока запрос реально уйдёт со СТАРЫМ токеном.
    await reachedNetwork.future;

    // Пользователь успешно вошёл заново, пока запрос был в полёте.
    await TokenStorage.instance
        .save(access: 'A-new', refresh: 'R-new', newSession: true);
    loggedInAgain.complete();

    final resp = await inFlight;

    expect(resp.statusCode, 200, reason: 'повтор ушёл со свежим токеном');
    expect(expiredCount, 0, reason: 'свежую сессию рвать нельзя');
    expect(await TokenStorage.instance.refreshToken, 'R-new');
    expect(calls.any((c) => c.contains('/auth/refresh')), isFalse,
        reason: 'чужой 401 не должен даже дёргать refresh');
    expect(calls.last, endsWith('#A-new'));
  });

  test('успешный refresh повторяет запрос со свежим токеном', () async {
    await TokenStorage.instance
        .save(access: 'A-1', refresh: 'R-1', newSession: true);

    ApiClient.instance.dio.httpClientAdapter = _FakeAdapter((o) async {
      calls.add('${o.path}#${bearerOf(o)}');
      if (o.path.endsWith('/auth/refresh')) {
        return (
          code: 200,
          body: {'access_token': 'A-2', 'refresh_token': 'R-2'},
        );
      }
      // Старый access отвергнут, новый принят.
      if (bearerOf(o) == 'A-1') return (code: 401, body: {'detail': 'expired'});
      return (code: 200, body: {'ok': true});
    });

    final resp = await ApiClient.instance.dio.get('https://x.test/orders');

    expect(resp.statusCode, 200);
    expect(expiredCount, 0);
    expect(await TokenStorage.instance.accessToken, 'A-2');
    expect(calls.last, endsWith('#A-2'),
        reason: 'повтор обязан уйти с новым токеном, а не со старым');
  });

  test('явный отказ refresh текущей сессии выводит на экран входа', () async {
    await TokenStorage.instance
        .save(access: 'A-dead', refresh: 'R-dead', newSession: true);

    ApiClient.instance.dio.httpClientAdapter = _FakeAdapter((o) async {
      calls.add(o.path);
      return (code: 401, body: {'detail': 'invalid refresh token'});
    });

    await expectLater(
      ApiClient.instance.dio.get('https://x.test/orders'),
      throwsA(isA<DioException>()),
    );

    expect(expiredCount, 1, reason: 'сессия действительно мертва');
    expect(await TokenStorage.instance.refreshToken, isNull);
  });

  test('сетевая ошибка refresh сессию не рвёт', () async {
    await TokenStorage.instance
        .save(access: 'A-net', refresh: 'R-net', newSession: true);

    ApiClient.instance.dio.httpClientAdapter = _FakeAdapter((o) async {
      if (o.path.endsWith('/auth/refresh')) {
        throw const SocketException('нет сети');
      }
      return (code: 401, body: {'detail': 'expired'});
    });

    await expectLater(
      ApiClient.instance.dio.get('https://x.test/orders'),
      throwsA(isA<DioException>()),
    );

    expect(expiredCount, 0, reason: 'метро и лифт — не повод требовать логин');
    expect(await TokenStorage.instance.refreshToken, 'R-net');
  });
}

// Локальный аналог dart:io SocketException — тест не тянет dart:io ради него.
class SocketException implements Exception {
  const SocketException(this.message);
  final String message;
  @override
  String toString() => 'SocketException: $message';
}
