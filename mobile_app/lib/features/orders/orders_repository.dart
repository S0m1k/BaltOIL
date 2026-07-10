import 'package:dio/dio.dart';
import 'package:uuid/uuid.dart';

import '../../core/api_client.dart';
import '../../core/app_config.dart';
import '../../core/outbox_db.dart';
import '../../core/sync_service.dart';
import 'order_models.dart';

/// Полдень UTC выбранного календарного дня (без сдвига через таймзоны).
/// showDatePicker отдаёт локальную дату; если слать её как есть, при чтении
/// из другой TZ день может «съехать» и заявка «на сегодня» покажется
/// просроченной. Полдень UTC сохраняет календарный день в любой зоне (±11ч).
/// Зеркалит веб-фикс (T12:00:00Z).
String _desiredDateIso(DateTime d) =>
    DateTime.utc(d.year, d.month, d.day, 12).toIso8601String();

class OrdersRepository {
  OrdersRepository._();
  static final OrdersRepository instance = OrdersRepository._();

  static const _uuid = Uuid();

  Dio get _dio => ApiClient.instance.dio;
  String get _base => AppConfig.orderBase;

  Future<List<Order>> list({int offset = 0, int limit = 50}) async {
    final resp = await _dio.get(
      '$_base/orders',
      queryParameters: {'offset': offset, 'limit': limit},
    );
    return (resp.data as List)
        .map((e) => Order.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// Полная карточка заявки (OrderResponse — включает status_logs).
  /// Частичное обновление заявки (веб orderPatch): смена заказчика,
  /// правка объёма/адреса/даты/топлива/стоимости staff'ом.
  Future<OrderDetail> patch(String orderId, Map<String, dynamic> body) async {
    final resp = await _dio.patch('$_base/orders/$orderId', data: body);
    return OrderDetail.fromJson(resp.data as Map<String, dynamic>);
  }

  Future<OrderDetail> getDetail(String orderId) async {
    final resp = await _dio.get('$_base/orders/$orderId');
    return OrderDetail.fromJson(resp.data as Map<String, dynamic>);
  }

  /// Список документов по заявке (staff: manager/admin; client тоже видит).
  Future<List<OrderDocument>> listDocuments(String orderId) async {
    final resp = await _dio.get('$_base/orders/$orderId/documents');
    return (resp.data as List)
        .map((e) => OrderDocument.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// Перенос заявки: передать хотя бы одно из [desiredDate] / [driverId].
  Future<OrderDetail> reschedule(
    String orderId, {
    DateTime? desiredDate,
    String? driverId,
  }) async {
    final resp = await _dio.post(
      '$_base/orders/$orderId/reschedule',
      data: {
        if (desiredDate != null) 'desired_date': _desiredDateIso(desiredDate),
        if (driverId != null) 'driver_id': driverId,
      },
    );
    return OrderDetail.fromJson(resp.data as Map<String, dynamic>);
  }

  /// Менеджер/admin: перевести заявку в другой статус.
  Future<OrderDetail> transition(
    String orderId,
    String toStatus, {
    String? comment,
  }) async {
    final resp = await _dio.post(
      '$_base/orders/$orderId/transition',
      data: {'to_status': toStatus, if (comment != null) 'comment': comment},
    );
    return OrderDetail.fromJson(resp.data as Map<String, dynamic>);
  }

  /// Водитель: принять назначенную заявку (new → accepted).
  Future<OrderDetail> accept(String orderId) async {
    final resp = await _dio.post(
      '$_base/orders/$orderId/transition',
      data: {'to_status': 'accepted', 'comment': 'Принята водителем'},
    );
    return OrderDetail.fromJson(resp.data as Map<String, dynamic>);
  }

  /// Менеджер/admin: зафиксировать оплату.
  Future<void> recordPaymentManager({
    required String orderId,
    required double amount,
    required String method,
    String? notes,
  }) async {
    await _dio.post(
      '$_base/payments/record',
      data: {
        'order_id': orderId,
        'amount': amount,
        'method': method,
        if (notes != null) 'notes': notes,
      },
    );
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

  /// Водитель: отметить доставку (accepted → delivered).
  ///
  /// Действие ставится в офлайн-очередь с уникальным idempotency_key и
  /// немедленно отправляется, если есть сеть. Возвращает обновлённый Order
  /// только при успешной немедленной синхронизации; при офлайне возвращает
  /// оптимистично обновлённую копию (status = delivered).
  Future<Order> markDelivered(String orderId) async {
    final key = _uuid.v4();
    final payload = <String, dynamic>{'to_status': 'delivered'};
    await OutboxDb.instance.enqueue(
      OutboxEntry(
        id: 0, // заполняется базой
        idempotencyKey: key,
        operation: 'transition',
        orderId: orderId,
        payload: payload,
        clientTs: DateTime.now(),
        status: 'pending',
        createdAt: DateTime.now(),
      ),
    );

    // Немедленная попытка отправки (если есть сеть — уйдёт синхронно).
    try {
      final resp = await _dio.post(
        '$_base/orders/$orderId/transition',
        data: {...payload, 'idempotency_key': key},
        options: Options(receiveTimeout: const Duration(seconds: 60)),
      );
      // Успех — помечаем в outbox synced (flush сделает это через SyncService,
      // но раз мы сами отправили — удаляем напрямую по idempotency_key).
      await _markSyncedByKey(key);
      return Order.fromJson(resp.data as Map<String, dynamic>);
    } on DioException catch (e) {
      final status = e.response?.statusCode;
      if (status != null && status >= 400 && status < 500) {
        // 4xx сразу — помечаем conflict, не оставляем в pending.
        await _markConflictByKey(
          key,
          'HTTP $status: ${e.response?.data?['detail'] ?? 'ошибка'}',
        );
        rethrow; // пробрасываем — _run() покажет snackbar
      }
      // Сеть недоступна / 5xx — оставляем pending, sync_service подберёт.
      // Возвращаем оптимистичную копию.
      SyncService.instance.flushNow(); // фоновая попытка
      return _optimisticDelivered(orderId);
    } catch (_) {
      SyncService.instance.flushNow();
      return _optimisticDelivered(orderId);
    }
  }

  /// Водитель: подтвердить изменения менеджера (pending_driver_ack → false).
  Future<void> ackChanges(String orderId) async {
    final key = _uuid.v4();
    final payload = <String, dynamic>{};
    await OutboxDb.instance.enqueue(
      OutboxEntry(
        id: 0,
        idempotencyKey: key,
        operation: 'ack_changes',
        orderId: orderId,
        payload: payload,
        clientTs: DateTime.now(),
        status: 'pending',
        createdAt: DateTime.now(),
      ),
    );

    try {
      await _dio.post(
        '$_base/orders/$orderId/ack-changes',
        data: {...payload, 'idempotency_key': key},
      );
      await _markSyncedByKey(key);
    } on DioException catch (e) {
      final status = e.response?.statusCode;
      if (status != null && status >= 400 && status < 500) {
        await _markConflictByKey(
          key,
          'HTTP $status: ${e.response?.data?['detail'] ?? 'ошибка'}',
        );
        rethrow;
      }
      SyncService.instance.flushNow();
      // ack — нет возвращаемого значения, молча проглатываем для UX офлайна.
    } catch (_) {
      SyncService.instance.flushNow();
    }
  }

  /// Водитель: зафиксировать оплату (только заявки физлиц — гарантирует бэк).
  Future<void> recordPayment({
    required String orderId,
    required double amount,
    required String method, // cash | card
    String? notes,
  }) async {
    final key = _uuid.v4();
    final payload = <String, dynamic>{
      'order_id': orderId,
      'amount': amount,
      'method': method,
      if (notes != null) 'notes': notes,
    };
    await OutboxDb.instance.enqueue(
      OutboxEntry(
        id: 0,
        idempotencyKey: key,
        operation: 'payment_record',
        orderId: orderId,
        payload: payload,
        clientTs: DateTime.now(),
        status: 'pending',
        createdAt: DateTime.now(),
      ),
    );

    try {
      await _dio.post(
        '$_base/payments/record',
        data: {...payload, 'idempotency_key': key},
      );
      await _markSyncedByKey(key);
    } on DioException catch (e) {
      final status = e.response?.statusCode;
      if (status != null && status >= 400 && status < 500) {
        await _markConflictByKey(
          key,
          'HTTP $status: ${e.response?.data?['detail'] ?? 'ошибка'}',
        );
        rethrow;
      }
      SyncService.instance.flushNow();
    } catch (_) {
      SyncService.instance.flushNow();
    }
  }

  /// Staff: сгенерировать счёт по заявке (invoice_preliminary | invoice_final).
  Future<void> generateInvoice(String orderId, String docType) async {
    await _dio.post(
      '$_base/orders/$orderId/documents/generate',
      data: {'doc_type': docType},
    );
  }

  /// Staff: отправить готовый документ в чат по заявке.
  Future<void> sendDocToChat(String orderId, String docId) async {
    await _dio.post(
      '$_base/orders/$orderId/documents/$docId/send',
      data: <String, dynamic>{},
    );
  }

  // --- вспомогательные ---

  Future<void> _markSyncedByKey(String key) async {
    final db = OutboxDb.instance;
    final rows = await db.listPending();
    for (final e in rows) {
      if (e.idempotencyKey == key) {
        await db.markSynced(e.id);
        await db.deleteSynced();
        break;
      }
    }
  }

  Future<void> _markConflictByKey(String key, String error) async {
    final db = OutboxDb.instance;
    final rows = await db.listPending();
    for (final e in rows) {
      if (e.idempotencyKey == key) {
        await db.markConflict(e.id, error);
        break;
      }
    }
  }

  /// Оптимистичная заглушка при офлайн-доставке: возвращает минимальный Order
  /// со статусом delivered. orderKind = '' → isIndividual=false, чтобы НЕ
  /// показывать диалог оплаты немедленно (водитель добавит оплату онлайн).
  Order _optimisticDelivered(String orderId) => Order(
    id: orderId,
    orderNumber: '—',
    orderKind: '', // не individual — диалог оплаты не появится офлайн
    fuelType: '',
    volumeRequested: 0,
    deliveryAddress: '',
    status: 'delivered',
    paymentStatus: 'unpaid',
    pendingDriverAck: false,
  );

  Future<Order> create({
    required String fuelType,
    required double volume,
    required String address,
    String paymentType = 'on_delivery',
    DateTime? desiredDate,
    String? comment,
    String? contactName,
    String? contactPhone,
    // Поля менеджера/админа (для клиента игнорируются на бэке).
    String? clientId,
    String? managerComment,
    String? driverId,
    bool isTtnL = false,
    bool allowDeliveryUnpaid = false,
    String? organizationId,
  }) async {
    final resp = await _dio.post(
      '$_base/orders',
      data: {
        'fuel_type': fuelType,
        'volume_requested': volume,
        'delivery_address': address,
        'payment_type': paymentType,
        if (desiredDate != null) 'desired_date': _desiredDateIso(desiredDate),
        if (comment != null && comment.isNotEmpty) 'client_comment': comment,
        if (contactName != null && contactName.isNotEmpty)
          'contact_person_name': contactName,
        if (contactPhone != null && contactPhone.isNotEmpty)
          'contact_person_phone': contactPhone,
        if (clientId != null) 'client_id': clientId,
        if (managerComment != null && managerComment.isNotEmpty)
          'manager_comment': managerComment,
        if (driverId != null) 'driver_id': driverId,
        if (isTtnL) 'is_ttn_l': true,
        if (allowDeliveryUnpaid) 'allow_delivery_unpaid': true,
        // «Оформить от имени» — организация клиента (веб: c-organization)
        if (organizationId != null) 'organization_id': organizationId,
      },
    );
    return Order.fromJson(resp.data as Map<String, dynamic>);
  }

  /// Доступные типы оплаты клиента (веб renderPaymentRadios):
  /// GET /tariffs/clients/{id}/payment-options.
  Future<({String clientType, List<String> types})> paymentOptions(
    String clientId,
  ) async {
    final resp = await _dio.get(
      '$_base/tariffs/clients/$clientId/payment-options',
    );
    final data = resp.data as Map<String, dynamic>;
    return (
      clientType: (data['client_type'] ?? '') as String,
      types: ((data['available_payment_types'] as List?) ?? const [])
          .map((e) => e.toString())
          .toList(),
    );
  }

  /// Сохранённые объекты доставки клиента (веб b815cf1, c-saved-object).
  /// Клиент — свои; staff — объекты выбранного клиента.
  Future<List<ClientObject>> clientObjects({String? clientId}) async {
    final resp = await _dio.get(
      '$_base/client-objects',
      queryParameters: {if (clientId != null) 'client_id': clientId},
    );
    return (resp.data as List)
        .map((e) => ClientObject.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> deleteClientObject(String id) async {
    await _dio.delete('$_base/client-objects/$id');
  }
}

/// Сохранённый объект доставки (ClientObjectResponse).
class ClientObject {
  const ClientObject({
    required this.id,
    required this.deliveryAddress,
    this.name,
  });

  final String id;
  final String deliveryAddress;
  final String? name;

  String get label =>
      name == null ? deliveryAddress : '$name — $deliveryAddress';

  factory ClientObject.fromJson(Map<String, dynamic> json) => ClientObject(
    id: (json['id'] as Object).toString(),
    deliveryAddress: (json['delivery_address'] ?? '') as String,
    name: json['name'] as String?,
  );
}
