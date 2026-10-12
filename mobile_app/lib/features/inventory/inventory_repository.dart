import 'package:dio/dio.dart';

import '../../core/api_client.dart';
import '../../core/app_config.dart';

/// FuelStockResponse — зеркало delivery_service/app/schemas/inventory.py.
class FuelStock {
  FuelStock({
    required this.fuelType,
    required this.fuelLabel,
    required this.currentVolume,
    required this.lastUpdated,
  });

  final String fuelType;
  final String fuelLabel;
  final double currentVolume;
  final DateTime lastUpdated;

  factory FuelStock.fromJson(Map<String, dynamic> json) => FuelStock(
        fuelType: json['fuel_type'] as String,
        fuelLabel: json['fuel_label'] as String,
        currentVolume: (json['current_volume'] as num).toDouble(),
        lastUpdated: DateTime.tryParse(
                (json['last_updated'] ?? '') as String) ??
            DateTime(2000),
      );
}

/// TransactionResponse — зеркало delivery_service/app/schemas/inventory.py.
class InventoryTransaction {
  InventoryTransaction({
    required this.id,
    required this.type,
    required this.fuelType,
    required this.fuelLabel,
    required this.volume,
    required this.transactionDate,
    required this.createdAt,
    this.tripId,
    this.orderId,
    this.orderNumber,
    this.clientName,
    this.driverName,
    this.supplierName,
    this.invoiceNumber,
    this.notes,
  });

  final String id;
  final String type; // arrival | departure
  final String fuelType;
  final String fuelLabel;
  final double volume;
  final DateTime transactionDate;
  final DateTime createdAt;
  final String? tripId;
  final String? orderId;
  final String? orderNumber;
  final String? clientName;
  final String? driverName;
  final String? supplierName;
  final String? invoiceNumber;
  final String? notes;

  factory InventoryTransaction.fromJson(Map<String, dynamic> json) =>
      InventoryTransaction(
        id: json['id'] as String,
        type: (json['type'] ?? '') as String,
        fuelType: (json['fuel_type'] ?? '') as String,
        fuelLabel: (json['fuel_label'] ?? '') as String,
        volume: (json['volume'] as num).toDouble(),
        transactionDate: DateTime.tryParse(
                (json['transaction_date'] ?? '') as String) ??
            DateTime(2000),
        createdAt: DateTime.tryParse(
                (json['created_at'] ?? '') as String) ??
            DateTime(2000),
        tripId: json['trip_id'] as String?,
        orderId: json['order_id'] as String?,
        orderNumber: json['order_number'] as String?,
        clientName: json['client_name'] as String?,
        driverName: json['driver_name'] as String?,
        supplierName: json['supplier_name'] as String?,
        invoiceNumber: json['invoice_number'] as String?,
        notes: json['notes'] as String?,
      );
}

/// TankResponse — зеркало delivery_service/app/schemas/tank.py (правки 2026-07-14).
class Tank {
  Tank({
    required this.id,
    required this.name,
    required this.fuelType,
    required this.currentVolume,
    required this.counter,
    required this.isActive,
    this.fuelLabel,
  });

  final String id;
  final String name;
  final String fuelType;
  final String? fuelLabel;
  final double currentVolume;
  final int counter;
  final bool isActive;

  /// Счётчик колонки — всегда 6 цифр с ведущими нулями (как fmtCounter веба).
  String get counterText => counter.toString().padLeft(6, '0');

  factory Tank.fromJson(Map<String, dynamic> json) => Tank(
        id: json['id'] as String,
        name: json['name'] as String,
        fuelType: json['fuel_type'] as String,
        fuelLabel: json['fuel_label'] as String?,
        currentVolume: (json['current_volume'] as num).toDouble(),
        counter: (json['counter'] as num).toInt(),
        isActive: (json['is_active'] ?? true) as bool,
      );
}

/// TankTxResponse — журнал операций по ёмкостям (было→стало + кто).
class TankTransaction {
  TankTransaction({
    required this.id,
    required this.tankId,
    required this.kind,
    required this.volume,
    required this.createdAt,
    this.tankName,
    this.counterBefore,
    this.counterAfter,
    this.orderNumber,
    this.peerTankName,
    this.actorName,
    this.notes,
  });

  final String id;
  final String tankId;
  final String? tankName;
  final String kind; // arrival | issue | transfer_in | transfer_out | adjust | expense
  final double volume;
  final int? counterBefore;
  final int? counterAfter;
  final String? orderNumber;
  final String? peerTankName;
  final String? actorName;
  final String? notes;
  final DateTime createdAt;

  factory TankTransaction.fromJson(Map<String, dynamic> json) =>
      TankTransaction(
        id: json['id'] as String,
        tankId: json['tank_id'] as String,
        tankName: json['tank_name'] as String?,
        kind: (json['kind'] ?? '') as String,
        volume: (json['volume'] as num).toDouble(),
        counterBefore: (json['counter_before'] as num?)?.toInt(),
        counterAfter: (json['counter_after'] as num?)?.toInt(),
        orderNumber: json['order_number'] as String?,
        peerTankName: json['peer_tank_name'] as String?,
        actorName: json['actor_name'] as String?,
        notes: json['notes'] as String?,
        createdAt:
            DateTime.tryParse((json['created_at'] ?? '') as String) ??
                DateTime(2000),
      );
}

class InventoryRepository {
  InventoryRepository._();
  static final InventoryRepository instance = InventoryRepository._();

  Dio get _dio => ApiClient.instance.dio;
  String get _base => AppConfig.deliveryBase;

  /// GET /inventory/stock — текущие остатки по каждому виду топлива.
  Future<List<FuelStock>> getStock() async {
    final resp = await _dio.get('$_base/inventory/stock');
    return (resp.data as List)
        .map((e) => FuelStock.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// GET /inventory/transactions — список операций прихода/расхода.
  Future<List<InventoryTransaction>> listTransactions({
    String? fuelType,
    String? type, // arrival | departure
    DateTime? dateFrom,
    DateTime? dateTo,
    int offset = 0,
    int limit = 100,
  }) async {
    final resp = await _dio.get(
      '$_base/inventory/transactions',
      queryParameters: {
        if (fuelType != null && fuelType.isNotEmpty) 'fuel_type': fuelType,
        if (type != null && type.isNotEmpty) 'type': type,
        if (dateFrom != null) 'date_from': dateFrom.toIso8601String(),
        if (dateTo != null) 'date_to': dateTo.toIso8601String(),
        'offset': offset,
        'limit': limit,
      },
    );
    return (resp.data as List)
        .map((e) =>
            InventoryTransaction.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// POST /inventory/arrivals — зафиксировать приход топлива.
  Future<InventoryTransaction> recordArrival({
    required String fuelType,
    required double volume,
    DateTime? transactionDate,
    String? supplierName,
    String? invoiceNumber,
    String? notes,
  }) async {
    final resp = await _dio.post(
      '$_base/inventory/arrivals',
      data: {
        'fuel_type': fuelType,
        'volume': volume,
        if (transactionDate != null)
          'transaction_date': transactionDate.toIso8601String(),
        if (supplierName != null && supplierName.isNotEmpty)
          'supplier_name': supplierName,
        if (invoiceNumber != null && invoiceNumber.isNotEmpty)
          'invoice_number': invoiceNumber,
        if (notes != null && notes.isNotEmpty) 'notes': notes,
      },
    );
    return InventoryTransaction.fromJson(
        resp.data as Map<String, dynamic>);
  }

  /// POST /inventory/expense — ручной расход «в бак / иное» (правки 2026-07-14).
  Future<void> recordExpense({
    required String fuelType,
    required double volume,
    required String expenseKind, // tank_refuel | other
    String? tankId,
    int? counterAfter,
    String? notes,
  }) async {
    await _dio.post(
      '$_base/inventory/expense',
      data: {
        'fuel_type': fuelType,
        'volume': volume,
        'expense_kind': expenseKind,
        if (tankId != null) 'tank_id': tankId,
        if (counterAfter != null) 'counter_after': counterAfter,
        if (notes != null && notes.isNotEmpty) 'notes': notes,
      },
    );
  }

  // ── Ёмкости (правки 2026-07-14) ────────────────────────────────

  /// GET /inventory/tanks — список ёмкостей (админ видит и скрытые).
  Future<List<Tank>> listTanks({bool includeInactive = false}) async {
    final resp = await _dio.get(
      '$_base/inventory/tanks',
      queryParameters: {if (includeInactive) 'include_inactive': true},
    );
    return (resp.data as List)
        .map((e) => Tank.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// GET /inventory/tanks/transactions — журнал операций по ёмкостям.
  Future<List<TankTransaction>> listTankTransactions({
    String? tankId,
    int limit = 200,
  }) async {
    final resp = await _dio.get(
      '$_base/inventory/tanks/transactions',
      queryParameters: {
        if (tankId != null) 'tank_id': tankId,
        'limit': limit,
      },
    );
    return (resp.data as List)
        .map((e) => TankTransaction.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// POST /inventory/tanks — создать ёмкость (только admin).
  Future<Tank> createTank({
    required String name,
    required String fuelType,
    double initialVolume = 0,
    int counter = 0,
  }) async {
    final resp = await _dio.post(
      '$_base/inventory/tanks',
      data: {
        'name': name,
        'fuel_type': fuelType,
        'initial_volume': initialVolume,
        'counter': counter,
      },
    );
    return Tank.fromJson(resp.data as Map<String, dynamic>);
  }

  /// PATCH /inventory/tanks/{id} — переименовать/сменить топливо/скрыть (admin).
  Future<Tank> updateTank(
    String tankId, {
    String? name,
    String? fuelType,
    bool? isActive,
  }) async {
    final resp = await _dio.patch(
      '$_base/inventory/tanks/$tankId',
      data: {
        if (name != null) 'name': name,
        if (fuelType != null) 'fuel_type': fuelType,
        if (isActive != null) 'is_active': isActive,
      },
    );
    return Tank.fromJson(resp.data as Map<String, dynamic>);
  }

  /// POST /inventory/tanks/{id}/adjust — точный остаток/счётчик (admin).
  Future<Tank> adjustTank(
    String tankId, {
    double? volume,
    int? counter,
    required String notes,
  }) async {
    final resp = await _dio.post(
      '$_base/inventory/tanks/$tankId/adjust',
      data: {
        if (volume != null) 'volume': volume,
        if (counter != null) 'counter': counter,
        'notes': notes,
      },
    );
    return Tank.fromJson(resp.data as Map<String, dynamic>);
  }

  /// POST /inventory/tanks/{id}/arrival — приход в ёмкость (водитель+).
  Future<Tank> tankArrival(
    String tankId, {
    required double volume,
    String? notes,
  }) async {
    final resp = await _dio.post(
      '$_base/inventory/tanks/$tankId/arrival',
      data: {
        'volume': volume,
        if (notes != null && notes.isNotEmpty) 'notes': notes,
      },
    );
    return Tank.fromJson(resp.data as Map<String, dynamic>);
  }

  /// POST /inventory/tanks/{id}/issue — выдача по счётчику (водитель+).
  /// Списанные литры = counter_after − текущий счётчик (через 999999).
  Future<void> tankIssue(
    String tankId, {
    required int counterAfter,
    String? orderId,
    String? orderNumber,
    double? volumeHint,
    String? notes,
  }) async {
    await _dio.post(
      '$_base/inventory/tanks/$tankId/issue',
      data: {
        'counter_after': counterAfter,
        if (orderId != null) 'order_id': orderId,
        if (orderNumber != null) 'order_number': orderNumber,
        if (volumeHint != null) 'volume_hint': volumeHint,
        if (notes != null && notes.isNotEmpty) 'notes': notes,
      },
    );
  }

  /// POST /inventory/tanks/transfer — перелив между ёмкостями (водитель+).
  Future<void> tankTransfer({
    required String fromTankId,
    required String toTankId,
    required double volume,
    String? notes,
  }) async {
    await _dio.post(
      '$_base/inventory/tanks/transfer',
      data: {
        'from_tank_id': fromTankId,
        'to_tank_id': toTankId,
        'volume': volume,
        if (notes != null && notes.isNotEmpty) 'notes': notes,
      },
    );
  }
}
