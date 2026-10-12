import 'dart:io';

import 'package:dio/dio.dart';
import 'package:dio/io.dart';
import 'package:flutter/foundation.dart';

import 'app_config.dart';
import 'token_storage.dart';

/// Один Dio на всё приложение. Интерцептор:
///  - подставляет Bearer из TokenStorage,
///  - на 401 делает refresh и повторяет запрос один раз (со СВЕЖИМ токеном),
///  - чистит сессию и зовёт onSessionExpired, только если сервер явно отверг
///    refresh-токен ТЕКУЩЕЙ сессии.
///
/// Про «выкидывает из аккаунта» (правки 2026-09-03). Пока пользователь вводит
/// логин, фоновые опросы (поллинг звонков раз в 4 с, outbox, WS) продолжают
/// стучаться со старым или отсутствующим токеном. Их 401 прилетал уже ПОСЛЕ
/// успешного входа и сносил свежую сессию: clear() + переход на экран входа.
/// Теперь у сессии есть номер (TokenStorage.generation), запрос помечается им
/// при отправке, и ответ из прошлой сессии не может ни закрыть новую, ни
/// перезаписать её токены результатом своего refresh.
class ApiClient {
  ApiClient._() {
    _dio = Dio(BaseOptions(
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 20),
    ));

    if (AppConfig.allowBadCertificates && !kReleaseMode) {
      // Локальная разработка: самоподписанный серт TLS-прокси.
      // В release-сборке никогда не отключаем проверку.
      (_dio.httpClientAdapter as IOHttpClientAdapter).createHttpClient = () {
        final client = HttpClient();
        client.badCertificateCallback = (cert, host, port) => true;
        return client;
      };
    }

    _dio.interceptors.add(InterceptorsWrapper(
      onRequest: (options, handler) async {
        if (options.extra['noAuth'] != true) {
          // Номер сессии на момент отправки: по нему в onError отличаем
          // «протухший хвост» прошлой сессии от 401 текущей.
          options.extra['authGen'] = TokenStorage.instance.generation;
          final token = await TokenStorage.instance.accessToken;
          if (token != null) {
            options.headers['Authorization'] = 'Bearer $token';
          }
        }
        handler.next(options);
      },
      onError: (error, handler) async {
        final response = error.response;
        final alreadyRetried = error.requestOptions.extra['retried'] == true;
        if (response?.statusCode == 401 &&
            !alreadyRetried &&
            error.requestOptions.extra['noAuth'] != true) {
          final sentGen = error.requestOptions.extra['authGen'] as int?;
          final currentGen = TokenStorage.instance.generation;

          // Ответ на запрос ПРОШЛОЙ сессии: пользователь за это время успел
          // войти заново. Такой 401 не говорит ничего о свежей сессии —
          // рвать её нельзя. Повторяем с актуальным токеном.
          if (sentGen != null && sentGen != currentGen) {
            final token = await TokenStorage.instance.accessToken;
            if (token == null) return handler.next(error);
            final opts = error.requestOptions
              ..extra['retried'] = true
              ..extra['authGen'] = currentGen
              ..headers['Authorization'] = 'Bearer $token';
            try {
              return handler.resolve(await _dio.fetch(opts));
            } on DioException catch (e) {
              return handler.next(e);
            }
          }

          final refreshed = await _tryRefresh();
          if (refreshed) {
            // Bearer ставим явно, хотя dio.fetch и прогоняет onRequest заново
            // (Dio 5.9): полагаться на это в повторе после refresh не хочется —
            // смена поведения пакета тихо вернула бы 401 в цикл.
            final token = await TokenStorage.instance.accessToken;
            final opts = error.requestOptions
              ..extra['retried'] = true
              ..extra['authGen'] = TokenStorage.instance.generation;
            if (token != null) {
              opts.headers['Authorization'] = 'Bearer $token';
            }
            try {
              final retry = await _dio.fetch(opts);
              return handler.resolve(retry);
            } on DioException catch (e) {
              return handler.next(e);
            }
          }
          // Выкидываем на экран входа ТОЛЬКО если сервер явно отверг
          // refresh-токен (правки 2026-07-24). Раньше любая сетевая ошибка
          // (таймаут, метро, лифт) чистила сессию и требовала логин заново.
          // И только если за время refresh не начался новый вход — иначе
          // снесём сессию, в которую пользователь уже успешно зашёл.
          if (_refreshRejected &&
              TokenStorage.instance.generation == currentGen) {
            await TokenStorage.instance.clear();
            onSessionExpired?.call();
          }
        }
        handler.next(error);
      },
    ));
  }

  static final ApiClient instance = ApiClient._();

  late final Dio _dio;
  Dio get dio => _dio;

  /// Назначается на старте приложения — навигация на экран входа.
  VoidCallback? onSessionExpired;

  /// Public wrapper — вызывается ws_client при 4401 (token expired).
  Future<bool> refreshTokenPublic() => _tryRefresh();

  /// Идущий сейчас refresh. Приложение шлёт запросы пачками (чаты, заявки,
  /// уведомления, WS), и при истёкшем access_token они получали 401 разом.
  /// Каждый дёргал refresh со СТАРЫМ токеном; сервер ротирует его при первом
  /// же обмене, а повторное предъявление считает кражей (reuse detection) и
  /// сносит всю цепочку сессий — отсюда и «постоянно выкидывает из аккаунта».
  /// Теперь refresh идёт один на всех: остальные ждут его результат.
  Future<bool>? _refreshInFlight;

  /// Сервер явно отверг refresh-токен (401/403) — сессия действительно мертва.
  /// Отличаем от сетевой ошибки, при которой сессию сохраняем.
  bool _refreshRejected = false;

  Future<bool> _tryRefresh() {
    return _refreshInFlight ??= _doRefresh().whenComplete(() {
      _refreshInFlight = null;
    });
  }

  Future<bool> _doRefresh() async {
    final gen = TokenStorage.instance.generation;
    final refresh = await TokenStorage.instance.refreshToken;
    if (refresh == null) {
      _refreshRejected = true; // токена нет — это не сетевая проблема
      return false;
    }
    try {
      final resp = await _dio.post(
        '${AppConfig.authBase}/auth/refresh',
        data: {'refresh_token': refresh},
        options: Options(extra: {'noAuth': true}),
      );
      // Пока ходили на сервер, пользователь мог войти заново. Сохранять пару
      // от старой сессии поверх новой нельзя: она уже не действует, и первый
      // же запрос с ней получит 401 — вход выглядел бы как «сразу выкинуло».
      if (TokenStorage.instance.generation != gen) {
        _refreshRejected = false;
        return false;
      }
      await TokenStorage.instance.save(
        access: resp.data['access_token'] as String,
        refresh: resp.data['refresh_token'] as String,
      );
      _refreshRejected = false;
      return true;
    } on DioException catch (e) {
      final code = e.response?.statusCode;
      // Отказ по уже сменившейся сессии текущей не касается.
      _refreshRejected = (code == 401 || code == 403) &&
          TokenStorage.instance.generation == gen;
      return false;
    } on Object {
      _refreshRejected = false; // непонятная ошибка — сессию не рвём
      return false;
    }
  }
}

/// Человекочитаемое сообщение из ошибки бэка (detail может быть строкой
/// или списком pydantic-ошибок).
String apiErrorMessage(Object error) {
  if (error is DioException) {
    final data = error.response?.data;
    if (data is Map && data['detail'] != null) {
      final detail = data['detail'];
      if (detail is String) return detail;
      if (detail is List && detail.isNotEmpty) {
        final first = detail.first;
        if (first is Map && first['msg'] != null) {
          return first['msg'] as String;
        }
      }
    }
    if (error.type == DioExceptionType.connectionTimeout ||
        error.type == DioExceptionType.connectionError) {
      return 'Нет связи с сервером. Проверьте интернет.';
    }
  }
  return 'Что-то пошло не так. Попробуйте ещё раз.';
}
