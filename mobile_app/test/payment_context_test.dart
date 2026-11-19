// Регрессия 19.11.2026: заявка юрлица с отгрузкой в долг уходила со статичным
// «По факту/Предоплата» и вставала в «ждём оплату».
import 'package:flutter_test/flutter_test.dart';
import 'package:baltoil_mobile/features/orders/payment_context.dart';

const _none = '__none__';
const _oneOff = '__oneoff__';

String? _cid({bool isStaff = true, String? selected, String? org}) =>
    paymentOptionsClientId(
      isStaff: isStaff,
      userId: 'admin-1',
      selectedClientId: selected,
      organizationId: org,
      noClientMarker: _none,
      oneOffMarker: _oneOff,
    );

void main() {
  group('paymentOptionsClientId', () {
    test(
      '«Без клиента» + организация: условия организации через сотрудника',
      () {
        expect(_cid(selected: _none, org: 'org-1'), 'admin-1');
      },
    );

    test('«Без клиента» без организации и разовый клиент — грузить нечего', () {
      expect(_cid(selected: _none), isNull);
      expect(_cid(selected: _oneOff, org: 'org-1'), isNull);
      expect(_cid(selected: null), isNull);
    });

    test('обычный клиент у сотрудника и клиент сам себе', () {
      expect(_cid(selected: 'client-7'), 'client-7');
      expect(_cid(isStaff: false), 'admin-1');
    });
  });

  group('paymentRadiosMatch', () {
    test('варианты не загружены — тип не отправляется', () {
      final expected = paymentCtxKey('admin-1', 'org-1');
      expect(paymentRadiosMatch(null, expected), isFalse);
    });

    test('загружены для другой организации — тип не отправляется', () {
      expect(
        paymentRadiosMatch(
          paymentCtxKey('admin-1', 'org-2'),
          paymentCtxKey('admin-1', 'org-1'),
        ),
        isFalse,
      );
    });

    test('загружены для этих клиента и организации — выбор уходит', () {
      final key = paymentCtxKey('admin-1', 'org-1');
      expect(paymentRadiosMatch(key, key), isTrue);
    });

    test('ожидаемого ключа нет — никогда не совпадает', () {
      expect(paymentRadiosMatch(null, null), isFalse);
      expect(paymentCtxKey(null, 'org-1'), isNull);
    });
  });

  group('defaultPaymentType', () {
    test('юрлицо с кредитом — «в долг», а не первый тип', () {
      expect(
        defaultPaymentType(
          types: const ['on_delivery', 'prepaid', 'debt'],
          creditAllowed: true,
        ),
        'debt',
      );
    });

    test('без кредита — первый доступный', () {
      expect(
        defaultPaymentType(
          types: const ['prepaid', 'on_delivery'],
          creditAllowed: false,
        ),
        'prepaid',
      );
    });

    test('кредит есть, но «в долг» недоступен — первый доступный', () {
      expect(
        defaultPaymentType(types: const ['prepaid'], creditAllowed: true),
        'prepaid',
      );
    });

    test('пустой список — по факту', () {
      expect(
        defaultPaymentType(types: const [], creditAllowed: false),
        'on_delivery',
      );
    });
  });
}
