@Tags(['live'])
library;

import 'dart:io';

import 'package:baltoil_mobile/core/app_config.dart';
import 'package:flutter_test/flutter_test.dart';

/// Живая проверка: доступен ли прод-бэкенд по тем самым URL, которые
/// зашиты в релизную сборку.
///
/// Регрессия на инцидент 06.09: релиз ушёл с дефолтом `10.0.2.2`, а прямые
/// порты 8001–8006 режутся мобильными операторами — приложение молчало.
/// Здесь мы бьём ровно по `AppConfig.*Base`, без хардкода адресов: если
/// кто-то снова поменяет дефолт на localhost или вернёт порты, тест это
/// поймает.
///
/// Тест ходит в сеть, поэтому помечен тегом `live` и по умолчанию пропущен
/// (см. dart_test.yaml). Запуск вручную:
///   flutter test --tags live --run-skipped test/prod_backend_reachability_test.dart
void main() {
  late HttpClient client;

  setUpAll(() {
    client = HttpClient()
      ..connectionTimeout = const Duration(seconds: 15)
      // Сертификат обязан быть валидным: релиз не отключает проверку.
      ..badCertificateCallback = (_, __, ___) => false;
  });

  tearDownAll(() => client.close(force: true));

  /// Возвращает HTTP-код или бросает с понятным текстом.
  /// Любой ответ сервера — успех связи; нас интересует именно «доехали».
  Future<int> status(String url, {String method = 'GET'}) async {
    final uri = Uri.parse(url);
    final req = await client.openUrl(method, uri);
    req.headers.set('content-type', 'application/json');
    if (method == 'POST') req.add('{}'.codeUnits);
    final resp = await req.close();
    await resp.drain<void>();
    return resp.statusCode;
  }

  group('Прод-бэкенд доступен по адресам релизной сборки', () {
    test('auth: логин отвечает, а не молчит', () async {
      final code = await status('${AppConfig.authBase}/auth/login', method: 'POST');
      // 401/422 — сервер разобрал запрос; главное, что это не таймаут.
      expect(code, anyOf(200, 400, 401, 422),
          reason: '${AppConfig.authBase}/auth/login вернул $code');
    });

    test('order: список заявок требует токен (значит, сервис жив)', () async {
      final code = await status('${AppConfig.orderBase}/orders');
      expect(code, anyOf(401, 403),
          reason: '${AppConfig.orderBase}/orders вернул $code');
    });

    test('order: API перевозки развёрнуто на проде', () async {
      final code = await status('${AppConfig.orderBase}/transport/bases');
      // 404 означал бы, что роутер перевозки не доехал до прода.
      expect(code, anyOf(401, 403),
          reason: '${AppConfig.orderBase}/transport/bases вернул $code');
    });

    test('delivery: зоны требуют токен', () async {
      final code = await status('${AppConfig.deliveryBase}/zones');
      expect(code, anyOf(401, 403),
          reason: '${AppConfig.deliveryBase}/zones вернул $code');
    });

    test('chat: health отвечает 200', () async {
      final code = await status('${AppConfig.chatBase}/health');
      expect(code, 200, reason: '${AppConfig.chatBase}/health вернул $code');
    });

    test('call: health отвечает 200', () async {
      final code = await status('${AppConfig.callBase}/health');
      expect(code, 200, reason: '${AppConfig.callBase}/health вернул $code');
    });

    test('APK на сайте отдаётся как пакет, а не как HTML страницы', () async {
      // Регрессия 07.09: /sztk.apk в нижнем регистре попадал в SPA-fallback
      // и вместо установщика скачивался index.html.
      for (final path in ['/SZTK.apk', '/sztk.apk']) {
        final uri = Uri.parse('https://${AppConfig.apiHost}$path');
        final req = await client.openUrl('HEAD', uri);
        final resp = await req.close();
        await resp.drain<void>();
        expect(resp.statusCode, 200, reason: '$path вернул ${resp.statusCode}');
        expect(
          resp.headers.contentType?.mimeType,
          'application/vnd.android.package-archive',
          reason: '$path отдаётся как ${resp.headers.contentType}',
        );
      }
    });

    test('прямые порты сервисов больше не используются приложением', () {
      // Дублирует app_config_test, но здесь это защита именно живого пути:
      // порт в URL = таймаут у части абонентов.
      for (final base in <String>[
        AppConfig.authBase,
        AppConfig.orderBase,
        AppConfig.deliveryBase,
        AppConfig.chatBase,
        AppConfig.notificationBase,
        AppConfig.callBase,
        AppConfig.wsBase,
      ]) {
        expect(RegExp(r':\d{4}').hasMatch(base), isFalse, reason: base);
      }
    });
  });
}
