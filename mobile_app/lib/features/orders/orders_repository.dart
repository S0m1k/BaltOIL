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
  Future<List<FuelType>> fuelTypes() async {
    final resp = await _dio.get('$_base/fuel-types');
    return (resp.data as List)
        .map((e) => FuelType.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<Order> create({
    required String fuelType,
    required double volume,
    required String address,
    DateTime? desiredDate,
    String? comment,
  }) async {
    final resp = await _dio.post('$_base/orders', data: {
      'fuel_type': fuelType,
      'volume_requested': volume,
      'delivery_address': address,
      if (desiredDate != null) 'desired_date': desiredDate.toIso8601String(),
      if (comment != null && comment.isNotEmpty) 'client_comment': comment,
    });
    return Order.fromJson(resp.data as Map<String, dynamic>);
  }
}
