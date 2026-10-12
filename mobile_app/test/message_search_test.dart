import 'package:baltoil_mobile/features/chat/chat_models.dart';
import 'package:flutter_test/flutter_test.dart';

/// Результат поиска по сообщениям (правки 2026-09-21): строка списка должна
/// сама знать, из какого она чата — второго запроса за названием нет.
void main() {
  MessageSearchResult parse(Map<String, dynamic> extra) =>
      MessageSearchResult.fromJson({
        'id': 'm1',
        'conversation_id': 'c1',
        'conversation_kind': 'staff_group',
        'sender_name': 'Волкова Ирина',
        'text': 'накладная во вложении',
        'created_at': '2026-09-21T08:30:00+00:00',
        ...extra,
      });

  test('разбирает ответ сервера целиком', () {
    final r = parse({'conversation_title': 'Бочки'});
    expect(r.id, 'm1');
    expect(r.conversationId, 'c1');
    expect(r.senderName, 'Волкова Ирина');
    expect(r.text, 'накладная во вложении');
    expect(r.createdAt.isUtc, isFalse); // показываем по местному времени
  });

  test('название группы берётся из заголовка чата', () {
    expect(parse({'conversation_title': 'Бочки'}).chatTitle, 'Бочки');
  });

  test('у штатных групп без заголовка — понятное имя', () {
    expect(parse({'conversation_group_code': 'work'}).chatTitle, 'Работа');
    expect(
      parse({'conversation_group_code': 'accounting'}).chatTitle,
      'Бухгалтерия',
    );
  });

  test('без заголовка и кода — подпись по типу чата', () {
    expect(
      parse({'conversation_kind': 'client_driver_order'}).chatTitle,
      'Заявка',
    );
    expect(parse({'conversation_kind': 'direct'}).chatTitle, 'Личный');
  });

  test('незнакомый тип чата не роняет список', () {
    expect(parse({'conversation_kind': 'нечто'}).chatTitle, 'Чат');
  });

  test('пустые поля от сервера переживаются', () {
    final r = MessageSearchResult.fromJson({
      'id': 'm2',
      'conversation_id': 'c2',
      'conversation_kind': 'direct',
      'sender_name': null,
      'text': null,
      'created_at': 'мусор',
    });
    expect(r.senderName, '');
    expect(r.text, '');
    expect(r.createdAt, isNotNull);
  });
}
