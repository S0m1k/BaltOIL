/// Модели перевозки (ТЗ 09.2026). Зеркалят схемы order_service:
/// app/schemas/transport.py — держим имена полей в snake_case как на бэке.
library;

/// Вид точки маршрута.
class RoutePointKind {
  static const oilDepot = 'oil_depot';       // нефтебаза из справочника
  static const base = 'base';                // наша база
  static const clientObject = 'client_object'; // объект клиента
}

/// Тип перевозки (блок 1 формы).
class TransportType {
  static const toBase = 'to_base';     // доставка на базу
  static const toClient = 'to_client'; // услуга доставки клиенту

  static String label(String? value) =>
      value == toClient ? 'Услуга доставки клиенту' : 'Доставка на базу';
}

/// Точка маршрута: вид + ссылка на справочник (или свободный текст).
class RoutePoint {
  const RoutePoint({required this.kind, this.id, this.text});

  final String kind;
  final String? id;
  final String? text;

  /// Ключ для сравнения и выбора в выпадающем списке.
  String get key => '$kind:${id ?? ''}';

  factory RoutePoint.fromJson(Map<String, dynamic> json) => RoutePoint(
    kind: (json['kind'] ?? '') as String,
    id: json['id'] as String?,
    text: json['text'] as String?,
  );

  Map<String, dynamic> toJson() => {
    'kind': kind,
    'id': id,
    if (text != null) 'text': text,
  };

  @override
  bool operator ==(Object other) =>
      other is RoutePoint && other.kind == kind && other.id == id;

  @override
  int get hashCode => Object.hash(kind, id);
}

/// Нефтебаза из справочника «Перевозка».
class TransportBase {
  const TransportBase({
    required this.id,
    required this.name,
    this.defaultDeliveryCost,
    this.isActive = true,
  });

  final String id;
  final String name;
  final double? defaultDeliveryCost;
  final bool isActive;

  factory TransportBase.fromJson(Map<String, dynamic> json) => TransportBase(
    id: json['id'] as String,
    name: (json['name'] ?? '') as String,
    defaultDeliveryCost: json['default_delivery_cost'] == null
        ? null
        : double.tryParse(json['default_delivery_cost'].toString()),
    isActive: (json['is_active'] ?? true) as bool,
  );

  RoutePoint get point => RoutePoint(kind: RoutePointKind.oilDepot, id: id);
}

/// Адрес объекта клиента.
class TransportClientAddress {
  const TransportClientAddress({required this.id, required this.address});

  final String id;
  final String address;

  factory TransportClientAddress.fromJson(Map<String, dynamic> json) =>
      TransportClientAddress(
        id: json['id'] as String,
        address: (json['address'] ?? '') as String,
      );
}

/// Объект клиента из справочника «Перевозка».
class TransportClientObject {
  const TransportClientObject({
    required this.id,
    required this.name,
    this.clientId,
    this.contractFileName,
    this.hasContract = false,
    this.isActive = true,
    this.addresses = const [],
  });

  final String id;
  final String name;
  final String? clientId;
  final String? contractFileName;
  final bool hasContract;
  final bool isActive;
  final List<TransportClientAddress> addresses;

  factory TransportClientObject.fromJson(Map<String, dynamic> json) =>
      TransportClientObject(
        id: json['id'] as String,
        name: (json['name'] ?? '') as String,
        clientId: json['client_id'] as String?,
        contractFileName: json['contract_file_name'] as String?,
        hasContract: (json['has_contract'] ?? false) as bool,
        isActive: (json['is_active'] ?? true) as bool,
        addresses: ((json['addresses'] ?? []) as List)
            .whereType<Map<String, dynamic>>()
            .map(TransportClientAddress.fromJson)
            .toList(),
      );

  RoutePoint get point => RoutePoint(kind: RoutePointKind.clientObject, id: id);
}

/// Оплата поставщику: сумма + дата (до 4 штук).
class SupplierPayment {
  const SupplierPayment({this.amount, this.date});

  final double? amount;
  final String? date;

  factory SupplierPayment.fromJson(Map<String, dynamic> json) => SupplierPayment(
    amount: json['amount'] == null
        ? null
        : double.tryParse(json['amount'].toString()),
    date: json['date']?.toString(),
  );

  Map<String, dynamic> toJson() => {
    'amount': amount?.toString(),
    'date': date,
  };

  bool get isEmpty => amount == null && (date == null || date!.isEmpty);
}

/// Детали перевозки. Блок 2 бэкенд обнуляет для не-staff, поэтому у водителя
/// финансовые поля приходят пустыми — это ожидаемо, а не ошибка загрузки.
class TransportDetail {
  const TransportDetail({
    required this.transportType,
    this.clientObjectId,
    this.routeFrom,
    this.routeTo,
    this.waypoints = const [],
    this.amountKg,
    this.amountL,
    this.desiredDateText,
    this.pricePerKg,
    this.pricePerL,
    this.density,
    this.totalAmount,
    this.supplierPayments = const [],
    this.deliveryPrice,
    this.deliveryPaid = false,
    this.driverPaymentAmount,
    this.driverPaymentPercent,
    this.supplierPaidTotal,
  });

  final String transportType;
  final String? clientObjectId;
  final RoutePoint? routeFrom;
  final RoutePoint? routeTo;
  final List<RoutePoint> waypoints;
  final double? amountKg;
  final double? amountL;
  final String? desiredDateText;

  // Блок 2 — только менеджеру и админу.
  final double? pricePerKg;
  final double? pricePerL;
  final double? density;
  final double? totalAmount;
  final List<SupplierPayment> supplierPayments;
  final double? deliveryPrice;
  final bool deliveryPaid;
  final double? driverPaymentAmount;
  final double? driverPaymentPercent;
  final double? supplierPaidTotal;

  bool get isToBase => transportType == TransportType.toBase;

  /// Заполнен ли служебный блок — водителю он не приходит вовсе.
  bool get hasFinance =>
      pricePerKg != null ||
      pricePerL != null ||
      totalAmount != null ||
      deliveryPrice != null ||
      driverPaymentAmount != null ||
      supplierPayments.isNotEmpty;

  static double? _num(dynamic v) =>
      v == null ? null : double.tryParse(v.toString());

  static RoutePoint? _point(dynamic v) => v is Map<String, dynamic>
      ? RoutePoint.fromJson(v)
      : null;

  factory TransportDetail.fromJson(Map<String, dynamic> json) => TransportDetail(
    transportType: (json['transport_type'] ?? TransportType.toBase) as String,
    clientObjectId: json['client_object_id'] as String?,
    routeFrom: _point(json['route_from']),
    routeTo: _point(json['route_to']),
    waypoints: ((json['waypoints'] ?? []) as List)
        .whereType<Map<String, dynamic>>()
        .map(RoutePoint.fromJson)
        .toList(),
    amountKg: _num(json['amount_kg']),
    amountL: _num(json['amount_l']),
    desiredDateText: json['desired_date_text'] as String?,
    pricePerKg: _num(json['price_per_kg']),
    pricePerL: _num(json['price_per_l']),
    density: _num(json['density']),
    totalAmount: _num(json['total_amount']),
    supplierPayments: ((json['supplier_payments'] ?? []) as List)
        .whereType<Map<String, dynamic>>()
        .map(SupplierPayment.fromJson)
        .toList(),
    deliveryPrice: _num(json['delivery_price']),
    deliveryPaid: (json['delivery_paid'] ?? false) as bool,
    driverPaymentAmount: _num(json['driver_payment_amount']),
    driverPaymentPercent: _num(json['driver_payment_percent']),
    supplierPaidTotal: _num(json['supplier_paid_total']),
  );
}

/// Формулы блока 2. Дублируют order_service/app/services/transport_formulas.py
/// как живая подсказка в форме; сервер остаётся источником истины.
class TransportFormulas {
  static const double defaultDriverPercent = 25;

  /// кол-во кг × плотность = кол-во литров.
  static double? litersFromKg(double? amountKg, double? density) {
    if (amountKg == null || density == null) return null;
    return double.parse((amountKg * density).toStringAsFixed(3));
  }

  /// итого, руб = кол-во × стоимость. Приоритет у пары «килограммы»,
  /// как на бэке: цена за кг — исходная цена закупки.
  static double? purchaseTotal({
    double? amountKg,
    double? amountL,
    double? pricePerKg,
    double? pricePerL,
  }) {
    if (amountKg != null && pricePerKg != null) {
      return double.parse((amountKg * pricePerKg).toStringAsFixed(2));
    }
    if (amountL != null && pricePerL != null) {
      return double.parse((amountL * pricePerL).toStringAsFixed(2));
    }
    return null;
  }

  /// оплата водителю = итого × процент / 100 (по умолчанию 25 %).
  static double? driverPayment(double? total, [double? percent]) {
    if (total == null) return null;
    final pct = percent ?? defaultDriverPercent;
    return double.parse((total * pct / 100).toStringAsFixed(2));
  }

  /// Сумма оплат поставщику: строки без суммы пропускаются.
  static double supplierPaymentsTotal(List<SupplierPayment> payments) {
    var total = 0.0;
    for (final p in payments) {
      if (p.amount != null) total += p.amount!;
    }
    return double.parse(total.toStringAsFixed(2));
  }
}
