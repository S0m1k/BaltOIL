import 'package:baltoil_mobile/features/notifications/notifications_repository.dart';
import 'package:flutter_test/flutter_test.dart';

/// Куда ведёт тап по уведомлению (правки 2026-09-14). Раньше в заявку не
/// вёл никакой: «новая заявка» и «изменения» открывались в никуда.
void main() {
  AppNotification notif({
    required String type,
    String? entityType,
    String? entityId,
  }) => AppNotification.fromJson({
    'id': 'n1',
    'type': type,
    'title': 'Заголовок',
    'body': 'Текст',
    'is_read': false,
    'entity_type': entityType,
    'entity_id': entityId,
  });

  group('уведомления о заявке', () {
    for (final type in ['order_created', 'order_status']) {
      test('$type с id заявки открывает заявку', () {
        final n = notif(type: type, entityType: 'order', entityId: 'ord-1');
        expect(n.opensOrder, isTrue);
        expect(n.opensChat, isFalse);
        expect(n.isNavigable, isTrue);
        expect(n.entityId, 'ord-1');
      });
    }

    test('без id заявки никуда не ведёт — открывать нечего', () {
      final n = notif(type: 'order_created', entityType: 'order');
      expect(n.opensOrder, isFalse);
      expect(n.isNavigable, isFalse);
    });
  });

  group('прочие уведомления', () {
    test('сообщение в чате ведёт в чат, а не в заявку', () {
      final n = notif(
        type: 'chat_message',
        entityType: 'conversation',
        entityId: 'conv-1',
      );
      expect(n.opensChat, isTrue);
      expect(n.opensOrder, isFalse);
    });

    test('готовый отчёт никуда не ведёт', () {
      final n = notif(
        type: 'report_ready',
        entityType: 'xlsx_download',
        entityId: 'file-1',
      );
      expect(n.isNavigable, isFalse);
    });

    test('уведомление о заявке без entity_type всё равно ведёт в заявку', () {
      // Старые записи: тип однозначно говорит, что id — это id заявки.
      final n = notif(type: 'order_status', entityId: 'ord-1');
      expect(n.entityType, isNull);
      expect(n.opensOrder, isTrue);
    });

    test('чужой entity_type под заказным типом в заявку не ведёт', () {
      final n = notif(
        type: 'order_created',
        entityType: 'xlsx_download',
        entityId: 'file-1',
      );
      expect(n.opensOrder, isFalse);
    });
  });
}
