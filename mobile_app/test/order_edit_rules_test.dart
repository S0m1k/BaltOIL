import 'package:baltoil_mobile/features/orders/order_edit_rules.dart';
import 'package:baltoil_mobile/features/orders/order_models.dart';
import 'package:baltoil_mobile/features/orders/orders_repository.dart';
import 'package:flutter_test/flutter_test.dart';

/// Правки 2026-09-28. Матрица обязана совпадать с вебом (canEditOrderFields,
/// _editPencil*) и бэкендом (order_service._check_edit_permissions,
/// _check_closed_order_edit) — иначе карандаш рисуется, а сервер отвечает 403.
const _me = 'user-1';
const _other = 'user-2';

bool _can(
  String field, {
  required String role,
  required String status,
  String? clientId,
  String? driverId,
}) =>
    canEditOrderField(
      field,
      role: role,
      userId: _me,
      status: status,
      clientId: clientId,
      driverId: driverId,
    );

void main() {
  group('админ и доставленные заявки (CRM-39)', () {
    for (final status in ['delivered', 'cancelled']) {
      test('админ правит «бумажные» поля в $status', () {
        for (final f in [
          'delivery_address',
          'contact_person_name',
          'contact_person_phone',
          'client_comment',
          'manager_comment',
          'delivery_cost',
          'fuel_cost',
          'desired_date',
          'organization_id',
        ]) {
          expect(_can(f, role: 'admin', status: status), isTrue, reason: f);
        }
      });

      test('объём и топливо в $status заморожены даже для админа', () {
        expect(_can('volume_requested', role: 'admin', status: status), isFalse);
        expect(_can('fuel_type', role: 'admin', status: status), isFalse);
      });

      test('менеджер $status не правит вовсе', () {
        expect(_can('manager_comment', role: 'manager', status: status),
            isFalse);
        expect(_can('delivery_address', role: 'manager', status: status),
            isFalse);
      });
    }

    test('в открытых статусах админ и менеджер правят всё', () {
      for (final role in ['admin', 'manager']) {
        for (final status in kOpenOrderStatuses) {
          for (final f in ['volume_requested', 'fuel_type', 'delivery_cost']) {
            expect(_can(f, role: role, status: status), isTrue,
                reason: '$role/$status/$f');
          }
        }
      }
    });
  });

  group('водитель (CRM-45)', () {
    test('в своей заявке правит контакт, адрес и оба комментария', () {
      for (final f in [
        'contact_person_name',
        'contact_person_phone',
        'client_comment',
        'manager_comment',
        'delivery_address',
      ]) {
        expect(_can(f, role: 'driver', status: 'accepted', driverId: _me),
            isTrue, reason: f);
      }
    });

    test('деньги и заказчика — нет', () {
      for (final f in ['delivery_cost', 'fuel_cost', 'organization_id']) {
        expect(_can(f, role: 'driver', status: 'accepted', driverId: _me),
            isFalse, reason: f);
      }
    });

    test('чужая, на согласовании или закрытая заявка — нет', () {
      expect(
          _can('client_comment',
              role: 'driver', status: 'accepted', driverId: _other),
          isFalse);
      expect(
          _can('client_comment',
              role: 'driver', status: 'awaiting_manager', driverId: _me),
          isFalse);
      expect(
          _can('client_comment',
              role: 'driver', status: 'delivered', driverId: _me),
          isFalse);
    });
  });

  group('клиент', () {
    test('свою открытую заявку правит, контакт и комментарии — нет', () {
      expect(_can('delivery_address', role: 'client', status: 'new',
          clientId: _me), isTrue);
      expect(_can('manager_comment', role: 'client', status: 'new',
          clientId: _me), isFalse);
      expect(_can('delivery_cost', role: 'client', status: 'new',
          clientId: _me), isFalse);
    });

    test('чужую или закрытую — нет', () {
      expect(_can('delivery_address', role: 'client', status: 'new',
          clientId: _other), isFalse);
      expect(_can('delivery_address', role: 'client', status: 'delivered',
          clientId: _me), isFalse);
    });
  });

  group('«Добавить НДС» к доставке', () {
    test('×1,22 как у зонной доставки юрлица', () {
      expect(withDeliveryVat('3500'), 4270);
      expect(withDeliveryVat('3200'), 3904);
    });

    test('запятая, пробелы и копейки половиной вверх', () {
      expect(withDeliveryVat(' 1234,55 '), 1506.15); // 1506,151
      expect(withDeliveryVat('0.25'), 0.31); // 0,305 → 0,31
      expect(withDeliveryVat('100.1'), 122.12);
    });

    test('пусто, ноль, минус и мусор — умножать нечего', () {
      for (final v in ['', '  ', '0', '-100', 'abc', 'NaN', 'Infinity']) {
        expect(withDeliveryVat(v), isNull, reason: v);
      }
    });

    test('поле ввода: рубли без «.0», копейки с двумя знаками', () {
      expect(formatDeliveryCostInput(4270), '4270');
      expect(formatDeliveryCostInput(1506.15), '1506.15');
      expect(formatDeliveryCostInput(122.1), '122.10');
    });
  });

  group('адрес в списках (CRM-37)', () {
    Order order(String address) => Order.fromJson({
          'id': 'o1',
          'order_number': 'ф1',
          'fuel_type': 'diesel_summer',
          'volume_requested': 1000,
          'delivery_address': address,
          'status': 'new',
        });

    test('пустой адрес — «Адрес уточняется»', () {
      expect(order('').addressLabel, 'Адрес уточняется');
      expect(order('   ').addressLabel, 'Адрес уточняется');
    });

    test('заполненный адрес — как есть', () {
      expect(order('СПб, Планерная 77').addressLabel, 'СПб, Планерная 77');
    });
  });

  group('сохранённый объект с контактом (CRM-45)', () {
    test('контакт приёмки читается из ответа', () {
      final o = ClientObject.fromJson({
        'id': 'x',
        'delivery_address': 'СПб, Планерная 77',
        'contact_person_name': 'Иван',
        'contact_person_phone': '+79990000000',
      });
      expect(o.contactPersonName, 'Иван');
      expect(o.contactPersonPhone, '+79990000000');
    });

    test('старые объекты без контакта не ломают разбор', () {
      final o = ClientObject.fromJson({'id': 1, 'delivery_address': 'A'});
      expect(o.id, '1');
      expect(o.contactPersonName, isNull);
      expect(o.contactPersonPhone, isNull);
    });
  });
}
