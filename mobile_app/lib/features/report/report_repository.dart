import 'package:dio/dio.dart';

import '../../core/api_client.dart';
import '../../core/app_config.dart';

/// Рейс из DriverReportResponse.trips — зеркало TripResponse (delivery_service).
class TripItem {
  TripItem({
    required this.id,
    required this.orderId,
    required this.status,
    required this.volumePlanned,
    this.volumeActual,
    this.departedAt,
    this.arrivedAt,
    this.deliveryAddress,
    this.invFuelType,
    this.invOrderNumber,
  });

  final String id;
  final String orderId;
  final String status; // pending | in_progress | completed | cancelled
  final double volumePlanned;
  final double? volumeActual;
  final DateTime? departedAt;
  final DateTime? arrivedAt;
  final String? deliveryAddress;
  final String? invFuelType;
  final String? invOrderNumber;

  factory TripItem.fromJson(Map<String, dynamic> json) => TripItem(
        id: json['id'] as String,
        orderId: json['order_id'] as String,
        status: (json['status'] ?? '') as String,
        volumePlanned: (json['volume_planned'] as num).toDouble(),
        volumeActual: json['volume_actual'] == null
            ? null
            : (json['volume_actual'] as num).toDouble(),
        departedAt: json['departed_at'] == null
            ? null
            : DateTime.tryParse(json['departed_at'] as String),
        arrivedAt: json['arrived_at'] == null
            ? null
            : DateTime.tryParse(json['arrived_at'] as String),
        deliveryAddress: json['delivery_address'] as String?,
        invFuelType: json['inv_fuel_type'] as String?,
        invOrderNumber: json['inv_order_number'] as String?,
      );
}

/// Ответ GET /reports/driver — зеркало DriverReportResponse (delivery_service).
class DriverReport {
  DriverReport({
    required this.driverId,
    required this.periodFrom,
    required this.periodTo,
    required this.totalTrips,
    required this.completedTrips,
    required this.cancelledTrips,
    required this.totalVolumePlanned,
    required this.totalVolumeActual,
    this.totalDistanceKm,
    required this.trips,
  });

  final String driverId;
  final DateTime periodFrom;
  final DateTime periodTo;
  final int totalTrips;
  final int completedTrips;
  final int cancelledTrips;
  final double totalVolumePlanned;
  final double totalVolumeActual;
  final double? totalDistanceKm;
  final List<TripItem> trips;

  factory DriverReport.fromJson(Map<String, dynamic> json) => DriverReport(
        driverId: json['driver_id'] as String,
        periodFrom:
            DateTime.tryParse(json['period_from'] as String) ?? DateTime(2000),
        periodTo:
            DateTime.tryParse(json['period_to'] as String) ?? DateTime(2000),
        totalTrips: (json['total_trips'] as num).toInt(),
        completedTrips: (json['completed_trips'] as num).toInt(),
        cancelledTrips: (json['cancelled_trips'] as num).toInt(),
        totalVolumePlanned:
            (json['total_volume_planned'] as num).toDouble(),
        totalVolumeActual:
            (json['total_volume_actual'] as num).toDouble(),
        totalDistanceKm: json['total_distance_km'] == null
            ? null
            : (json['total_distance_km'] as num).toDouble(),
        trips: (json['trips'] as List)
            .map((e) => TripItem.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

/// Синглтон-репозиторий для отчётов водителя.
///
/// Endpoint: GET  /api/v1/reports/driver   (delivery_service, порт 8003)
///           POST /api/v1/reports/driver/xlsx — формирует XLSX асинхронно и
///           отправляет уведомление со ссылкой на скачивание (TODO мобилка).
class ReportRepository {
  ReportRepository._();
  static final ReportRepository instance = ReportRepository._();

  Dio get _dio => ApiClient.instance.dio;
  String get _base => AppConfig.deliveryBase;

  /// Отчёт по рейсам водителя за период.
  ///
  /// [driverId] — UUID водителя.
  /// [dateFrom] / [dateTo] — границы периода (ISO 8601).
  ///
  /// Бэк проверяет права: водитель может запросить только собственный отчёт.
  Future<DriverReport> driverReport({
    required String driverId,
    required DateTime dateFrom,
    required DateTime dateTo,
  }) async {
    final resp = await _dio.get(
      '$_base/reports/driver',
      queryParameters: {
        'driver_id': driverId,
        'date_from': dateFrom.toIso8601String(),
        'date_to': dateTo.toIso8601String(),
      },
    );
    return DriverReport.fromJson(resp.data as Map<String, dynamic>);
  }

  /// Запустить генерацию XLSX-отчёта на сервере.
  ///
  /// Сервер формирует файл в фоне и присылает push-уведомление со ссылкой
  /// POST /api/v1/reports/driver/xlsx → 202 Accepted.
  ///
  /// TODO (мобилка): реализовать скачивание файла по download_url из
  /// уведомления через dio + path_provider (сохранить во временную директорию
  /// и открыть через open_filex или share_plus).
  Future<void> requestDriverReportXlsx({
    required String driverId,
    required DateTime dateFrom,
    required DateTime dateTo,
  }) async {
    await _dio.post(
      '$_base/reports/driver/xlsx',
      queryParameters: {
        'driver_id': driverId,
        'date_from': dateFrom.toIso8601String(),
        'date_to': dateTo.toIso8601String(),
      },
    );
  }
}
