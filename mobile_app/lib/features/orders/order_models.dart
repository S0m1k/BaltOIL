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

/// Кэш каталога топлива: code → label («ДТ-Л К5» вместо diesel_summer).
/// Заполняется из GET /fuel-types; до загрузки — фолбэк-подписи как на вебе.
class FuelCatalog {
  FuelCatalog._();

  static final Map<String, String> _labels = {
    'diesel_summer': 'ДТ-Л К5',
    'diesel_winter': 'ДТ-З К5',
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
