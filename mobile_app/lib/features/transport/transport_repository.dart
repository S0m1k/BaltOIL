import 'package:dio/dio.dart';
import 'package:uuid/uuid.dart';

import '../../core/api_client.dart';
import '../../core/app_config.dart';
import '../orders/order_models.dart';
import 'transport_models.dart';

/// Доступ к API перевозки (ТЗ 09.2026): справочники, заявки, окно доставки.
///
/// Справочники бэкенд отдаёт только менеджеру и админу — у водителя запросы
/// падают с 403. Поэтому [loadDirectory] умеет возвращать пустые списки:
/// имена точек маршрута водителю приходят в самом маршруте заявки
/// (delivery_address), а выбор точек в окне доставки собирается из уже
/// сохранённых значений.
class TransportRepository {
  TransportRepository._();
  static final TransportRepository instance = TransportRepository._();

  static const _uuid = Uuid();

  Dio get _dio => ApiClient.instance.dio;
  String get _base => AppConfig.orderBase;

  // ── Справочники ────────────────────────────────────────────────────────────

  Future<List<TransportBase>> listBases() async {
    final resp = await _dio.get('$_base/transport/bases');
    return (resp.data as List)
        .whereType<Map<String, dynamic>>()
        .map(TransportBase.fromJson)
        .toList();
  }

  Future<List<TransportClientObject>> listClientObjects() async {
    final resp = await _dio.get('$_base/transport/client-objects');
    return (resp.data as List)
        .whereType<Map<String, dynamic>>()
        .map(TransportClientObject.fromJson)
        .toList();
  }

  /// Оба справочника разом. Водителю (403) отдаём пустые списки вместо
  /// исключения — экран перевозки должен открываться и без них.
  Future<({List<TransportBase> bases, List<TransportClientObject> objects})>
      loadDirectory() async {
    try {
      final results = await Future.wait([listBases(), listClientObjects()]);
      return (
        bases: results[0] as List<TransportBase>,
        objects: results[1] as List<TransportClientObject>,
      );
    } on DioException catch (e) {
      if (e.response?.statusCode == 403) {
        return (bases: <TransportBase>[], objects: <TransportClientObject>[]);
      }
      rethrow;
    }
  }

  Future<TransportBase> createBase({
    required String name,
    double? defaultDeliveryCost,
  }) async {
    final resp = await _dio.post('$_base/transport/bases', data: {
      'name': name,
      'default_delivery_cost': defaultDeliveryCost,
    });
    return TransportBase.fromJson(resp.data as Map<String, dynamic>);
  }

  Future<TransportBase> updateBase(
    String id, {
    String? name,
    double? defaultDeliveryCost,
  }) async {
    final resp = await _dio.patch('$_base/transport/bases/$id', data: {
      'name': ?name,
      'default_delivery_cost': defaultDeliveryCost,
    });
    return TransportBase.fromJson(resp.data as Map<String, dynamic>);
  }

  Future<void> deleteBase(String id) =>
      _dio.delete('$_base/transport/bases/$id');

  Future<TransportClientObject> createClientObject({
    required String name,
    String? clientId,
    List<String> addresses = const [],
  }) async {
    final resp = await _dio.post('$_base/transport/client-objects', data: {
      'name': name,
      'client_id': clientId,
      'addresses': addresses,
    });
    return TransportClientObject.fromJson(resp.data as Map<String, dynamic>);
  }

  Future<TransportClientObject> updateClientObject(
    String id, {
    String? name,
    String? clientId,
    List<String>? addresses,
  }) async {
    final resp = await _dio.patch('$_base/transport/client-objects/$id', data: {
      'name': ?name,
      'client_id': clientId,
      'addresses': ?addresses,
    });
    return TransportClientObject.fromJson(resp.data as Map<String, dynamic>);
  }

  Future<void> deleteClientObject(String id) =>
      _dio.delete('$_base/transport/client-objects/$id');

  // ── Заявки на перевозку ────────────────────────────────────────────────────

  Future<TransportDetail> getDetail(String orderId) async {
    final resp = await _dio.get('$_base/transport/orders/$orderId');
    return TransportDetail.fromJson(resp.data as Map<String, dynamic>);
  }

  Future<Order> create(Map<String, dynamic> body) async {
    final resp = await _dio.post('$_base/transport/orders', data: body);
    return Order.fromJson(resp.data as Map<String, dynamic>);
  }

  Future<Order> update(String orderId, Map<String, dynamic> body) async {
    final resp = await _dio.patch('$_base/transport/orders/$orderId', data: body);
    return Order.fromJson(resp.data as Map<String, dynamic>);
  }

  /// Окно «Доставлена» у водителя: маршрут и дата обязательны, комментарий —
  /// единственное необязательное поле (ТЗ, п. 3).
  ///
  /// В отличие от обычной доставки здесь нет outbox: перевозка требует
  /// подтверждения маршрута, а разрешать офлайн-правку справочных ссылок
  /// значит рисковать конфликтом с правками менеджера. Ключ идемпотентности
  /// шлём всё равно — повторный тап при плохой связи не создаст второй переход.
  Future<Order> deliver(
    String orderId, {
    required RoutePoint routeFrom,
    required RoutePoint routeTo,
    List<RoutePoint> waypoints = const [],
    required String desiredDateText,
    String? comment,
  }) async {
    final resp = await _dio.post(
      '$_base/transport/orders/$orderId/deliver',
      data: {
        'route_from': routeFrom.toJson(),
        'route_to': routeTo.toJson(),
        'waypoints': waypoints.map((w) => w.toJson()).toList(),
        'desired_date_text': desiredDateText,
        if (comment != null && comment.isNotEmpty) 'comment': comment,
        'idempotency_key': _uuid.v4(),
      },
    );
    return Order.fromJson(resp.data as Map<String, dynamic>);
  }
}
