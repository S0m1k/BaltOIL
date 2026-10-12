import 'package:baltoil_mobile/core/app_config.dart';
import 'package:flutter_test/flutter_test.dart';

/// Регрессия на «приложение не коннектится к бэку»: релизная сборка
/// собирается БЕЗ --dart-define, поэтому дефолты обязаны указывать на прод
/// и на шлюз 443, а не на 10.0.2.2 / порты сервисов.
void main() {
  group('AppConfig по умолчанию (без dart-define)', () {
    test('хост — прод, а не адрес эмулятора', () {
      expect(AppConfig.apiHost, 'crm.9171517.ru');
      expect(AppConfig.apiHost, isNot(contains('10.0.2.2')));
      expect(AppConfig.apiHost, isNot(contains('localhost')));
    });

    test('прямые порты сервисов выключены', () {
      expect(AppConfig.useDirectPorts, isFalse);
    });

    test('проверка сертификата включена', () {
      expect(AppConfig.allowBadCertificates, isFalse);
    });

    test('все базовые URL идут по https через 443 без порта', () {
      final bases = <String>[
        AppConfig.authBase,
        AppConfig.orderBase,
        AppConfig.deliveryBase,
        AppConfig.chatBase,
        AppConfig.notificationBase,
        AppConfig.callBase,
      ];
      for (final base in bases) {
        expect(base, startsWith('https://crm.9171517.ru/'), reason: base);
        expect(base, isNot(matches(r':\d+')), reason: base);
      }
    });

    test('префиксы шлюза совпадают с nginx и веб-фронтом', () {
      expect(AppConfig.authBase, 'https://crm.9171517.ru/api/auth/api/v1');
      expect(AppConfig.orderBase, 'https://crm.9171517.ru/api/order/api/v1');
      expect(
        AppConfig.deliveryBase,
        'https://crm.9171517.ru/api/delivery/api/v1',
      );
      expect(AppConfig.chatBase, 'https://crm.9171517.ru/api/chat');
      expect(AppConfig.notificationBase, 'https://crm.9171517.ru/api/notif/api/v1');
      expect(AppConfig.callBase, 'https://crm.9171517.ru/api/call');
    });

    test('WebSocket чата — wss через тот же шлюз', () {
      expect(AppConfig.wsBase, 'wss://crm.9171517.ru/api/chat');
    });
  });
}
