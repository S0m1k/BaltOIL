/// Модели заявок — поля соответствуют OrderListResponse order_service.
class Order {
  Order({
    required this.id,
    required this.orderNumber,
    required this.orderKind,
    required this.fuelType,
    required this.volumeRequested,
    required this.deliveryAddress,
    required this.status,
    required this.paymentStatus,
    required this.pendingDriverAck,
    this.driverId,
    this.expectedAmount,
    this.finalAmount,
    this.desiredDate,
    this.createdAt,
    this.clientComment,
    this.managerComment,
    this.buyerName,
  });

  final String id;
  final String orderNumber;
  final String orderKind; // individual | company | ttn_l
  final String fuelType;
  final double volumeRequested;
  final String deliveryAddress;
  final String status;
  final String paymentStatus;
  final bool pendingDriverAck;
  final String? driverId;
  final double? expectedAmount;
  final double? finalAmount;
  final DateTime? desiredDate;
  final DateTime? createdAt;
  final String? clientComment;
  final String? managerComment;

  /// Имя организации или клиента-заказчика (веб d29807a) — null у физлица.
  final String? buyerName;

  bool get isIndividual => orderKind == 'individual';

  factory Order.fromJson(Map<String, dynamic> json) => Order(
        id: json['id'] as String,
        orderNumber: json['order_number'] as String,
        orderKind: (json['order_kind'] ?? '') as String,
        fuelType: json['fuel_type'] as String,
        volumeRequested: (json['volume_requested'] as num).toDouble(),
        deliveryAddress: json['delivery_address'] as String,
        status: json['status'] as String,
        paymentStatus: (json['payment_status'] ?? '') as String,
        pendingDriverAck: (json['pending_driver_ack'] ?? false) as bool,
        driverId: json['driver_id'] as String?,
        expectedAmount: json['expected_amount'] == null
            ? null
            : double.tryParse(json['expected_amount'].toString()),
        finalAmount: json['final_amount'] == null
            ? null
            : double.tryParse(json['final_amount'].toString()),
        desiredDate: json['desired_date'] == null
            ? null
            : DateTime.tryParse(json['desired_date'] as String),
        createdAt: json['created_at'] == null
            ? null
            : DateTime.tryParse(json['created_at'] as String),
        clientComment: json['client_comment'] as String?,
        managerComment: json['manager_comment'] as String?,
        buyerName: json['buyer_name'] as String?,
      );
}

/// Статусы — подписи и цвета 1:1 с вебом (STATUS_LABELS + --s-* переменные
/// в frontend/index.html).
const orderStatusLabels = <String, String>{
  'new': 'Новая',
  'accepted': 'Принята водителем',
  'delivered': 'Доставлена',
  'cancelled': 'Отменена',
  // Легаси-статусы старых заявок до Д1 — показываем как есть.
  'pending': 'Ожидает',
  'confirmed': 'Подтверждена',
  'in_transit': 'В пути',
  'rejected': 'Отклонена',
};

String orderStatusLabel(String status) => orderStatusLabels[status] ?? status;

/// Цвета статусов с веба: --s-new #3b82f6, --s-progress #d97706,
/// --s-delivered #0d9488, --s-rejected #dc2626, --s-closed #6b7280.
const orderStatusColors = <String, int>{
  'new': 0xFF3B82F6,
  'accepted': 0xFFD97706,
  'delivered': 0xFF0D9488,
  'cancelled': 0xFFDC2626,
  'rejected': 0xFFDC2626,
  'in_transit': 0xFF7C3AED,
};

/// Полная карточка заявки (GET /orders/{id} — OrderResponse).
/// Расширяет [Order] полями, которые не входят в OrderListResponse.
class OrderDetail extends Order {
  OrderDetail({
    required super.id,
    required super.orderNumber,
    required super.orderKind,
    required super.fuelType,
    required super.volumeRequested,
    required super.deliveryAddress,
    required super.status,
    required super.paymentStatus,
    required super.pendingDriverAck,
    super.driverId,
    super.expectedAmount,
    super.finalAmount,
    super.desiredDate,
    super.createdAt,
    super.clientComment,
    super.managerComment,
    super.buyerName,
    this.clientId,
    this.managerId,
    this.volumeDelivered,
    this.contactPersonName,
    this.contactPersonPhone,
    this.ttnNumber,
    this.paymentType,
    this.rejectionReason,
    this.deliveryZoneName,
    this.deliveryCost,
    this.paidTotal = 0.0,
    this.debtAmount = 0.0,
    this.allowDeliveryUnpaid = false,
    this.pricingWarning = false,
    this.statusLogs = const [],
    this.pendingChangedFields = const [],
  });

  final String? clientId;
  final String? managerId;
  final double? volumeDelivered;
  final String? contactPersonName;
  final String? contactPersonPhone;
  final String? ttnNumber;
  final String? paymentType; // on_delivery | prepaid | trade_credit | ...
  final String? rejectionReason;
  final String? deliveryZoneName;
  final double? deliveryCost;
  final double paidTotal;
  final double debtAmount;
  final bool allowDeliveryUnpaid;
  final bool pricingWarning;
  final List<OrderStatusLog> statusLogs;
  final List<String> pendingChangedFields;

  factory OrderDetail.fromJson(Map<String, dynamic> json) => OrderDetail(
        id: json['id'] as String,
        orderNumber: json['order_number'] as String,
        orderKind: (json['order_kind'] ?? '') as String,
        fuelType: json['fuel_type'] as String,
        volumeRequested:
            (json['volume_requested'] as num).toDouble(),
        deliveryAddress: json['delivery_address'] as String,
        status: json['status'] as String,
        paymentStatus: (json['payment_status'] ?? '') as String,
        pendingDriverAck:
            (json['pending_driver_ack'] ?? false) as bool,
        driverId: json['driver_id'] as String?,
        expectedAmount: json['expected_amount'] == null
            ? null
            : double.tryParse(json['expected_amount'].toString()),
        finalAmount: json['final_amount'] == null
            ? null
            : double.tryParse(json['final_amount'].toString()),
        desiredDate: json['desired_date'] == null
            ? null
            : DateTime.tryParse(json['desired_date'] as String),
        createdAt: json['created_at'] == null
            ? null
            : DateTime.tryParse(json['created_at'] as String),
        clientComment: json['client_comment'] as String?,
        managerComment: json['manager_comment'] as String?,
        buyerName: json['buyer_name'] as String?,
        clientId: json['client_id'] as String?,
        managerId: json['manager_id'] as String?,
        volumeDelivered: json['volume_delivered'] == null
            ? null
            : (json['volume_delivered'] as num).toDouble(),
        contactPersonName: json['contact_person_name'] as String?,
        contactPersonPhone: json['contact_person_phone'] as String?,
        ttnNumber: json['ttn_number'] as String?,
        paymentType: json['payment_type'] as String?,
        rejectionReason: json['rejection_reason'] as String?,
        deliveryZoneName: json['delivery_zone_name'] as String?,
        deliveryCost: json['delivery_cost'] == null
            ? null
            : double.tryParse(json['delivery_cost'].toString()),
        paidTotal: (json['paid_total'] as num? ?? 0).toDouble(),
        debtAmount: (json['debt_amount'] as num? ?? 0).toDouble(),
        allowDeliveryUnpaid:
            (json['allow_delivery_unpaid'] ?? false) as bool,
        pricingWarning:
            (json['pricing_warning'] ?? false) as bool,
        statusLogs: (json['status_logs'] as List? ?? [])
            .map((e) =>
                OrderStatusLog.fromJson(e as Map<String, dynamic>))
            .toList(),
        pendingChangedFields:
            (json['pending_changed_fields'] as List? ?? [])
                .map((e) => e as String)
                .toList(),
      );
}

/// Запись журнала смены статуса (OrderStatusLogResponse).
class OrderStatusLog {
  OrderStatusLog({
    required this.id,
    required this.toStatus,
    this.fromStatus,
    this.changedByRole,
    this.comment,
    this.createdAt,
  });

  final String id;
  final String? fromStatus;
  final String toStatus;
  final String? changedByRole;
  final String? comment;
  final DateTime? createdAt;

  factory OrderStatusLog.fromJson(Map<String, dynamic> json) =>
      OrderStatusLog(
        id: json['id'] as String,
        fromStatus: json['from_status'] as String?,
        toStatus: json['to_status'] as String,
        changedByRole: json['changed_by_role'] as String?,
        comment: json['comment'] as String?,
        createdAt: json['created_at'] == null
            ? null
            : DateTime.tryParse(json['created_at'] as String),
      );
}

/// Документ по заявке (DocumentResponse).
class OrderDocument {
  OrderDocument({
    required this.id,
    required this.orderId,
    required this.docType,
    required this.docNumber,
    required this.status,
    this.totalAmount,
    this.volume,
    this.issuedAt,
  });

  final String id;
  final String orderId;
  final String docType; // invoice_preliminary | invoice_final | ...
  final String docNumber;
  final String status; // draft | ready | sent | cancelled
  final double? totalAmount;
  final double? volume;
  final DateTime? issuedAt;

  factory OrderDocument.fromJson(Map<String, dynamic> json) =>
      OrderDocument(
        id: json['id'] as String,
        orderId: json['order_id'] as String,
        docType: json['doc_type'] as String,
        docNumber: json['doc_number'] as String,
        status: json['status'] as String,
        totalAmount: json['total_amount'] == null
            ? null
            : (json['total_amount'] as num).toDouble(),
        volume: json['volume'] == null
            ? null
            : (json['volume'] as num).toDouble(),
        issuedAt: json['issued_at'] == null
            ? null
            : DateTime.tryParse(json['issued_at'] as String),
      );
}

/// Кэш каталога топлива: code → label («ДТ-Л К5» вместо diesel_summer).
/// Заполняется из GET /fuel-types; до загрузки — фолбэк-подписи как на вебе.
class FuelCatalog {
  FuelCatalog._();

  static final Map<String, String> _labels = {
    'diesel_summer': 'ДТ – Л – К5',
    'diesel_winter': 'ДТ – З – К5',
    'petrol_92': 'АИ-92',
    'petrol_95': 'АИ-95',
    'fuel_oil': 'М-100',
  };

  static void update(List<FuelType> types) {
    for (final t in types) {
      _labels[t.code] = t.label;
    }
  }

  static String label(String code) => _labels[code] ?? code;
}

class FuelType {
  FuelType({required this.code, required this.label});

  final String code;
  final String label;

  factory FuelType.fromJson(Map<String, dynamic> json) => FuelType(
        code: json['code'] as String,
        label: json['label'] as String,
      );
}
