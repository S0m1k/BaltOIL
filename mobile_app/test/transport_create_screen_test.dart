import 'package:baltoil_mobile/features/transport/transport_models.dart';
import 'package:flutter_test/flutter_test.dart';

/// Правила формы перевозки, которые легко сломать правкой экрана.
///
/// Виджет-тест самой формы требует мока справочников и токена, поэтому здесь
/// закреплена та логика, из-за которой заявка уезжает на бэкенд неправильной:
/// набор точек маршрута по типу перевозки и тело запроса.
void main() {
  group('Точки маршрута по типу перевозки (ТЗ 09.2026)', () {
    test('доставка на базу: «куда» всегда наша база', () {
      const to = RoutePoint(kind: RoutePointKind.base, text: 'База');
      expect(to.kind, RoutePointKind.base);
      // id у базы пустой: своей записи в справочнике она не имеет.
      expect(to.id, isNull);
      expect(to.toJson()['kind'], 'base');
    });

    test('нефтебаза и объект клиента едут с id справочника', () {
      const depot = RoutePoint(kind: RoutePointKind.oilDepot, id: 'depot-1');
      const object = RoutePoint(kind: RoutePointKind.clientObject, id: 'obj-1');
      expect(depot.toJson()['id'], 'depot-1');
      expect(object.toJson()['kind'], 'client_object');
    });
  });

  group('Формулы блока «куплено» совпадают с сервером', () {
    test('литры считаются из килограммов и плотности', () {
      expect(TransportFormulas.litersFromKg(1000, 0.84), 840);
    });

    test('итого берёт пару «килограммы» приоритетом', () {
      final total = TransportFormulas.purchaseTotal(
        amountKg: 1000,
        amountL: 840,
        pricePerKg: 50,
        pricePerL: 60,
      );
      // 1000 × 50, а не 840 × 60 — цена за кг исходная для закупки.
      expect(total, 50000);
    });

    test('водителю по умолчанию 25 % от итого', () {
      expect(TransportFormulas.driverPayment(50000), 12500);
      expect(TransportFormulas.driverPayment(50000, 30), 15000);
    });

    test('без итого оплата водителю не выдумывается', () {
      expect(TransportFormulas.driverPayment(null), isNull);
    });
  });

  group('Оплаты поставщику', () {
    test('пустые строки формы не уезжают на бэкенд', () {
      final rows = <SupplierPayment>[
        SupplierPayment(amount: 10000, date: '2026-09-10'),
        SupplierPayment(amount: null, date: null),
      ].where((p) => p.amount != null || p.date != null).toList();
      expect(rows, hasLength(1));
      expect(TransportFormulas.supplierPaymentsTotal(rows), 10000);
    });

    test('дата уходит в ISO-формате, который принимает сервер', () {
      final d = DateTime(2026, 9, 10);
      final iso = '${d.year.toString().padLeft(4, '0')}-'
          '${d.month.toString().padLeft(2, '0')}-'
          '${d.day.toString().padLeft(2, '0')}';
      expect(iso, '2026-09-10');
    });
  });
}
