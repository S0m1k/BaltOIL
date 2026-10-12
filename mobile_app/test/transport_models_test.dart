import 'package:baltoil_mobile/features/orders/order_models.dart';
import 'package:baltoil_mobile/features/transport/transport_models.dart';
import 'package:flutter_test/flutter_test.dart';

/// Модели и формулы перевозки (ТЗ 09.2026). Формулы обязаны совпадать с
/// order_service/app/services/transport_formulas.py — расхождение означает,
/// что подсказка в форме врёт относительно того, что сохранит сервер.
void main() {
  group('RoutePoint', () {
    test('ключ склеивает вид и id, пустой id не ломает формат', () {
      expect(const RoutePoint(kind: 'oil_depot', id: 'abc').key, 'oil_depot:abc');
      expect(const RoutePoint(kind: 'base').key, 'base:');
    });

    test('равенство по виду и id, текст не влияет', () {
      const a = RoutePoint(kind: 'base', text: 'База');
      const b = RoutePoint(kind: 'base', text: 'Наша база');
      const c = RoutePoint(kind: 'client_object', id: 'x');
      expect(a, equals(b));
      expect(a.hashCode, equals(b.hashCode));
      expect(a, isNot(equals(c)));
    });

    test('round-trip через JSON сохраняет вид и id', () {
      final json = const RoutePoint(kind: 'client_object', id: 'obj-1').toJson();
      expect(json['kind'], 'client_object');
      expect(json['id'], 'obj-1');
      final back = RoutePoint.fromJson(json);
      expect(back, const RoutePoint(kind: 'client_object', id: 'obj-1'));
    });

    test('пустой JSON не бросает исключение', () {
      final p = RoutePoint.fromJson(<String, dynamic>{});
      expect(p.kind, '');
      expect(p.id, isNull);
    });
  });

  group('TransportDetail.fromJson', () {
    test('разбирает полный ответ staff со всеми блоками', () {
      final d = TransportDetail.fromJson({
        'transport_type': 'to_base',
        'route_from': {'kind': 'oil_depot', 'id': 'base-1'},
        'route_to': {'kind': 'base', 'text': 'База'},
        'waypoints': [
          {'kind': 'client_object', 'id': 'obj-1'},
        ],
        'amount_kg': '3000',
        'amount_l': '2520.0',
        'desired_date_text': 'до 15 сентября',
        'price_per_kg': '90',
        'density': '0.84',
        'total_amount': '270000.00',
        'supplier_payments': [
          {'amount': '100000', 'date': '2026-09-01'},
          {'amount': '170000', 'date': '2026-09-05'},
        ],
        'driver_payment_amount': '67500.00',
        'driver_payment_percent': '25',
        'supplier_paid_total': '270000.00',
      });

      expect(d.isToBase, isTrue);
      expect(d.routeFrom, const RoutePoint(kind: 'oil_depot', id: 'base-1'));
      expect(d.routeTo?.kind, 'base');
      expect(d.waypoints, hasLength(1));
      expect(d.amountKg, 3000);
      expect(d.amountL, 2520.0);
      expect(d.desiredDateText, 'до 15 сентября');
      expect(d.pricePerKg, 90);
      expect(d.totalAmount, 270000.00);
      expect(d.supplierPayments, hasLength(2));
      expect(d.hasFinance, isTrue);
    });

    test('ответ водителю без блока 2 — это не ошибка, просто пустые финансы', () {
      final d = TransportDetail.fromJson({
        'transport_type': 'to_client',
        'route_from': {'kind': 'base', 'text': 'База'},
        'route_to': {'kind': 'client_object', 'id': 'obj-9'},
        'waypoints': <dynamic>[],
        'desired_date_text': 'завтра утром',
        'supplier_payments': <dynamic>[],
        'delivery_paid': false,
      });

      expect(d.isToBase, isFalse);
      expect(d.hasFinance, isFalse);
      expect(d.totalAmount, isNull);
      expect(d.desiredDateText, 'завтра утром');
    });

    test('числа приходят строками (Decimal на бэке) и парсятся', () {
      final d = TransportDetail.fromJson({
        'transport_type': 'to_client',
        'delivery_price': '4270.50',
        'driver_payment_percent': '25.00',
      });
      expect(d.deliveryPrice, 4270.50);
      expect(d.driverPaymentPercent, 25.0);
    });
  });

  group('TransportFormulas — зеркало transport_formulas.py', () {
    test('кол-во кг × плотность = литры, округление до 3 знаков', () {
      expect(TransportFormulas.litersFromKg(3000, 0.84), 2520.0);
      expect(TransportFormulas.litersFromKg(1234, 0.8365), 1032.241);
    });

    test('без кг или без плотности литры не считаются', () {
      expect(TransportFormulas.litersFromKg(null, 0.84), isNull);
      expect(TransportFormulas.litersFromKg(3000, null), isNull);
    });

    test('итого считается по паре «кг», она приоритетнее литров', () {
      final total = TransportFormulas.purchaseTotal(
        amountKg: 3000,
        pricePerKg: 90,
        amountL: 2520,
        pricePerL: 100,
      );
      expect(total, 270000.00);
    });

    test('если пара по кг неполная — считаем по литрам', () {
      final total = TransportFormulas.purchaseTotal(
        amountKg: 3000,
        amountL: 2520,
        pricePerL: 100,
      );
      expect(total, 252000.00);
    });

    test('без цен итого не считается', () {
      expect(TransportFormulas.purchaseTotal(amountKg: 3000), isNull);
      expect(TransportFormulas.purchaseTotal(), isNull);
    });

    test('оплата водителю — 25 % по умолчанию', () {
      expect(TransportFormulas.driverPayment(270000), 67500.00);
      expect(TransportFormulas.defaultDriverPercent, 25);
    });

    test('процент водителю можно задать свой', () {
      expect(TransportFormulas.driverPayment(270000, 10), 27000.00);
      expect(TransportFormulas.driverPayment(100, 33.33), 33.33);
    });

    test('без итого оплата водителю не считается', () {
      expect(TransportFormulas.driverPayment(null), isNull);
    });

    test('сумма оплат поставщику пропускает строки без суммы', () {
      final total = TransportFormulas.supplierPaymentsTotal(const [
        SupplierPayment(amount: 100000, date: '2026-09-01'),
        SupplierPayment(date: '2026-09-02'),
        SupplierPayment(amount: 70000),
      ]);
      expect(total, 170000.00);
    });

    test('пустой список оплат даёт ноль, а не null', () {
      expect(TransportFormulas.supplierPaymentsTotal(const []), 0.0);
    });
  });

  group('Order.isTransport', () {
    Order make(String kind) => Order(
      id: 'o1',
      orderNumber: 'ТТН-1',
      orderKind: kind,
      fuelType: 'diesel_summer',
      volumeRequested: 0,
      deliveryAddress: 'Нефтебаза → База',
      status: 'accepted',
      paymentStatus: 'unpaid',
      pendingDriverAck: false,
    );

    test('перевозка отличается от прочих видов заявки', () {
      expect(make('transport').isTransport, isTrue);
      expect(make('individual').isTransport, isFalse);
      expect(make('company').isTransport, isFalse);
      expect(make('ttn_l').isTransport, isFalse);
    });

    test('перевозка не считается физлицом — денег водитель не собирает', () {
      expect(make('transport').isIndividual, isFalse);
    });
  });

  group('TransportType', () {
    test('подписи типов на русском', () {
      expect(TransportType.label('to_base'), 'Доставка на базу');
      expect(TransportType.label('to_client'), 'Услуга доставки клиенту');
      expect(TransportType.label(null), 'Доставка на базу');
    });
  });
}
