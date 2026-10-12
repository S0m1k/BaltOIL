import 'package:baltoil_mobile/features/chat/chat_models.dart';
import 'package:flutter_test/flutter_test.dart';

/// CRM-47: состав приватной группы меняют админ и создатель чата — те же
/// права, что check_group_manage_access в chat_service.
Conversation _conv({
  String kind = 'staff_group',
  String? groupCode = 'custom-abc',
  String createdById = 'creator',
}) =>
    Conversation.fromJson({
      'id': 'c1',
      'kind': kind,
      'group_code': groupCode,
      'created_by_id': createdById,
      'created_by_role': 'manager',
      'updated_at': '2026-09-28T10:00:00Z',
    });

void main() {
  group('isPrivateGroup', () {
    test('custom-группа — приватная', () {
      expect(_conv().isPrivateGroup, isTrue);
    });

    test('штатные «Работа»/«Бухгалтерия» и прочие диалоги — нет', () {
      expect(_conv(groupCode: 'work').isPrivateGroup, isFalse);
      expect(_conv(groupCode: 'accounting').isPrivateGroup, isFalse);
      expect(_conv(groupCode: null).isPrivateGroup, isFalse);
      expect(_conv(kind: 'client_manager').isPrivateGroup, isFalse);
    });
  });

  group('canManageMembers', () {
    test('админ управляет любой приватной группой', () {
      expect(_conv().canManageMembers(userId: 'someone', role: 'admin'),
          isTrue);
    });

    test('создатель управляет своей группой', () {
      expect(_conv().canManageMembers(userId: 'creator', role: 'manager'),
          isTrue);
    });

    test('обычный участник — нет', () {
      expect(_conv().canManageMembers(userId: 'someone', role: 'manager'),
          isFalse);
      expect(_conv().canManageMembers(userId: 'someone', role: 'driver'),
          isFalse);
    });

    test('в штатной группе состав ролевой — не управляет даже админ', () {
      expect(
          _conv(groupCode: 'work')
              .canManageMembers(userId: 'creator', role: 'admin'),
          isFalse);
    });
  });

  test('ChatMember: имя из ответа, без имени — начало id', () {
    final named = ChatMember.fromJson({
      'user_id': '12345678-aaaa',
      'user_role': 'driver',
      'full_name': 'Пётр',
    });
    expect(named.label, 'Пётр');
    expect(named.role, 'driver');
    final anon =
        ChatMember.fromJson({'user_id': '12345678-aaaa', 'user_role': 'admin'});
    expect(anon.label, '12345678');
  });
}
