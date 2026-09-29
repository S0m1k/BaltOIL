import 'package:dio/dio.dart';

import '../../core/api_client.dart';
import '../../core/app_config.dart';
import 'order_models.dart';

class OrdersRepository {
  OrdersRepository._();
  static final OrdersRepository instance = OrdersRepository._();

  Dio get _dio => ApiClient.instance.dio;
  String get _base => AppConfig.orderBase;

  Future<List<Order>> list({int offset = 0, int limit = 50}) async {
    final resp = await _dio.get('$_base/orders',
        queryParameters: {'offset': offset, 'limit': limit});
    return (resp.data as List)
        .map((e) => Order.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// Клиенту бэк отдаёт только топливо в наличии (Д2).
  /// Попутно обновляет кэш подписей FuelCatalog (code → label).
  Future<List<FuelType>> fuelTypes() async {
    final resp = await _dio.get('$_base/fuel-types');
    final types = (resp.data as List)
        .map((e) => FuelType.fromJson(e as Map<String, dynamic>))
        .toList();
    FuelCatalog.update(types);
    return types;
  }

  /// Водитель: взять свободную заявку из пула (new → accepted).
  Future<Order> claim(String orderId) async {
    final resp = await _dio.post('$_base/orders/$orderId/claim', data: {});
    return Order.fromJson(resp.data as Map<String, dynamic>);
  }

  /// Водитель: отметить доставку (accepted → delivered). ТТН бэк сгенерирует сам.
  ///
  /// Тяжёлый эндпоинт: бэк синхронно создаёт счёт и списывает топливо через
  /// delivery_service — на холодном старте может идти десятки секунд.
  Future<Order> markDelivered(String orderId) async {
    final resp = await _dio.post(
      '$_base/orders/$orderId/transition',
      data: {'to_status': 'delivered'},
      options: Options(receiveTimeout: const Duration(seconds: 60)),
    );
    return Order.fromJson(resp.data as Map<String, dynamic>);
  }

  /// Водитель: подтвердить изменения менеджера (pending_driver_ack → false).
  Future<void> ackChanges(String orderId) =>
      _dio.post('$_base/orders/$orderId/ack-changes', data: {});

  /// Водитель: зафиксировать оплату (только заявки физлиц — гарантирует бэк).
  Future<void> recordPayment({
    required String orderId,
    required double amount,
    required String method, // cash | card
  }) =>
      _dio.post('$_base/payments/record', data: {
        'order_id': orderId,
        'amount': amount,
        'method': method,
      });

  Future<Order> create({
    required String fuelType,
    required double volume,
    required String address,
    String paymentType = 'on_delivery',
    DateTime? desiredDate,
    String? comment,
  }) async {
    final resp = await _dio.post('$_base/orders', data: {
      'fuel_type': fuelType,
      'volume_requested': volume,
      'delivery_address': address,
      'payment_type': paymentType,
      if (desiredDate != null) 'desired_date': desiredDate.toIso8601String(),
      if (comment != null && comment.isNotEmpty) 'client_comment': comment,
    });
    return Order.fromJson(resp.data as Map<String, dynamic>);
  }
}
