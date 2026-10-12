import 'package:dio/dio.dart';

import '../../core/api_client.dart';
import '../../core/app_config.dart';

/// PaymentResponse — зеркало PaymentResponse из order_service/app/routers/payments.py.
class Payment {
  Payment({
    required this.id,
    required this.orderId,
    required this.clientId,
    required this.kind,
    required this.status,
    required this.amount,
    required this.createdAt,
    this.method,
    this.invoiceNumber,
    this.paidAt,
    this.notes,
  });

  final String id;
  final String orderId;
  final String clientId;
  final String kind; // prepayment | delivery | invoice | adjustment
  final String status; // pending | paid | cancelled | refunded
  final String? method; // cash | card | bank_transfer | ...
  final double amount;
  final String? invoiceNumber;
  final DateTime? paidAt;
  final String? notes;
  final DateTime createdAt;

  factory Payment.fromJson(Map<String, dynamic> json) => Payment(
        id: json['id'] as String,
        orderId: json['order_id'] as String,
        clientId: json['client_id'] as String,
        kind: (json['kind'] ?? '') as String,
        status: (json['status'] ?? '') as String,
        method: json['method'] as String?,
        amount: (json['amount'] as num).toDouble(),
        invoiceNumber: json['invoice_number'] as String?,
        paidAt: json['paid_at'] == null
            ? null
            : DateTime.tryParse(json['paid_at'] as String),
        notes: json['notes'] as String?,
        createdAt: DateTime.tryParse(
                (json['created_at'] ?? '') as String) ??
            DateTime(2000),
      );
}

/// Сводка по отчёту (GET /payments/report).
class PaymentReport {
  PaymentReport({
    required this.totalPaid,
    required this.totalPending,
    required this.totalCancelled,
    required this.count,
  });

  final double totalPaid;
  final double totalPending;
  final double totalCancelled;
  final int count;

  factory PaymentReport.fromJson(Map<String, dynamic> json) => PaymentReport(
        totalPaid:
            (json['total_paid'] as num? ?? 0).toDouble(),
        totalPending:
            (json['total_pending'] as num? ?? 0).toDouble(),
        totalCancelled:
            (json['total_cancelled'] as num? ?? 0).toDouble(),
        count: (json['count'] as num? ?? 0).toInt(),
      );
}

class FinanceRepository {
  FinanceRepository._();
  static final FinanceRepository instance = FinanceRepository._();

  Dio get _dio => ApiClient.instance.dio;
  String get _base => AppConfig.orderBase;

  /// GET /payments — список платежей с фильтрами.
  Future<List<Payment>> listPayments({
    DateTime? dateFrom,
    DateTime? dateTo,
    String? status,
    int offset = 0,
    int limit = 100,
  }) async {
    final resp = await _dio.get(
      '$_base/payments',
      queryParameters: {
        if (dateFrom != null) 'date_from': dateFrom.toIso8601String(),
        if (dateTo != null) 'date_to': dateTo.toIso8601String(),
        if (status != null && status.isNotEmpty) 'status': status,
        'offset': offset,
        'limit': limit,
      },
    );
    return (resp.data as List)
        .map((e) => Payment.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// GET /payments/report — итоговые суммы за период.
  Future<PaymentReport> report({
    DateTime? dateFrom,
    DateTime? dateTo,
  }) async {
    final resp = await _dio.get(
      '$_base/payments/report',
      queryParameters: {
        if (dateFrom != null) 'date_from': dateFrom.toIso8601String(),
        if (dateTo != null) 'date_to': dateTo.toIso8601String(),
      },
    );
    return PaymentReport.fromJson(resp.data as Map<String, dynamic>);
  }
}
