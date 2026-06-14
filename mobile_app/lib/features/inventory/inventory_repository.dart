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
}
