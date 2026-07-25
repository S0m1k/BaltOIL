import 'dart:io';

import 'package:dio/dio.dart';
import 'package:dio/io.dart';
import 'package:flutter/foundation.dart';

import 'app_config.dart';
import 'token_storage.dart';

/// Один Dio на всё приложение. Интерцептор:
///  - подставляет Bearer из TokenStorage,
///  - на 401 делает refresh и повторяет запрос один раз,
///  - если refresh не удался — чистит сессию и зовёт onSessionExpired.
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
          final refreshed = await _tryRefresh();
          if (refreshed) {
            final opts = error.requestOptions..extra['retried'] = true;
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
          if (_refreshRejected) {
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
      await TokenStorage.instance.save(
        access: resp.data['access_token'] as String,
        refresh: resp.data['refresh_token'] as String,
      );
      _refreshRejected = false;
      return true;
    } on DioException catch (e) {
      final code = e.response?.statusCode;
      _refreshRejected = code == 401 || code == 403;
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
