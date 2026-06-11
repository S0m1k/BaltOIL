/// Модели заявок — поля соответствуют OrderListResponse order_service.
class Order {
  Order({
    required this.id,
    required this.orderNumber,
    required this.fuelType,
    required this.volumeRequested,
    required this.deliveryAddress,
    required this.status,
    required this.paymentStatus,
    this.expectedAmount,
    this.desiredDate,
    this.createdAt,
    this.clientComment,
  });

  final String id;
  final String orderNumber;
  final String fuelType;
  final double volumeRequested;
  final String deliveryAddress;
  final String status;
  final String paymentStatus;
  final double? expectedAmount;
  final DateTime? desiredDate;
  final DateTime? createdAt;
  final String? clientComment;

  factory Order.fromJson(Map<String, dynamic> json) => Order(
        id: json['id'] as String,
        orderNumber: json['order_number'] as String,
        fuelType: json['fuel_type'] as String,
        volumeRequested: (json['volume_requested'] as num).toDouble(),
        deliveryAddress: json['delivery_address'] as String,
        status: json['status'] as String,
        paymentStatus: (json['payment_status'] ?? '') as String,
        expectedAmount: json['expected_amount'] == null
            ? null
            : double.tryParse(json['expected_amount'].toString()),
        desiredDate: json['desired_date'] == null
            ? null
            : DateTime.tryParse(json['desired_date'] as String),
        createdAt: json['created_at'] == null
            ? null
            : DateTime.tryParse(json['created_at'] as String),
        clientComment: json['client_comment'] as String?,
      );
}

/// Статусы — русские подписи, как на вебе (Новая → Принята → Доставлена).
const orderStatusLabels = <String, String>{
  'new': 'Новая',
  'accepted': 'Принята',
  'delivered': 'Доставлена',
  'cancelled': 'Отменена',
  // Легаси-статусы старых заявок до Д1 — показываем как есть.
  'pending': 'Ожидает',
  'confirmed': 'Подтверждена',
  'in_transit': 'В пути',
  'rejected': 'Отклонена',
};

String orderStatusLabel(String status) => orderStatusLabels[status] ?? status;

class FuelType {
  FuelType({required this.code, required this.label});

  final String code;
  final String label;

  factory FuelType.fromJson(Map<String, dynamic> json) => FuelType(
        code: json['code'] as String,
        label: json['label'] as String,
      );
}
