import 'package:dio/dio.dart';

import '../../core/api_client.dart';
import '../../core/app_config.dart';

// ---------------------------------------------------------------------------
// Models
// ---------------------------------------------------------------------------

/// Статусы рейса (delivery_service TripStatus).
enum TripStatus {
  planned,
  inTransit,
  completed,
  cancelled;

  static TripStatus fromString(String s) => switch (s) {
        'planned' => planned,
        'in_transit' => inTransit,
        'completed' => completed,
        'cancelled' => cancelled,
        _ => planned,
      };

  String toApiString() => switch (this) {
        TripStatus.planned => 'planned',
        TripStatus.inTransit => 'in_transit',
        TripStatus.completed => 'completed',
        TripStatus.cancelled => 'cancelled',
      };
}

const Map<TripStatus, String> kTripStatusLabels = {
  TripStatus.planned: 'Запланирован',
  TripStatus.inTransit: 'В пути',
  TripStatus.completed: 'Завершён',
  TripStatus.cancelled: 'Отменён',
};

class Trip {
  Trip({
    required this.id,
    required this.orderId,
    required this.driverId,
    required this.status,
    required this.volumePlanned,
    this.vehicleId,
    this.volumeActual,
    this.departedAt,
    this.arrivedAt,
    this.deliveryAddress,
    this.driverNotes,
    this.isArchived = false,
    required this.createdAt,
    required this.updatedAt,
    this.invFuelType,
    this.invOrderNumber,
    this.invClientId,
    this.invClientName,
    this.invDriverName,
  });

  final String id;
  final String orderId;
  final String driverId;
  final String? vehicleId;
  final TripStatus status;
  final double volumePlanned;
  final double? volumeActual;
  final DateTime? departedAt;
  final DateTime? arrivedAt;
  final String? deliveryAddress;
  final String? driverNotes;
  final bool isArchived;
  final DateTime createdAt;
  final DateTime updatedAt;

  // Denormalised inventory context (filled by manager at trip creation).
  final String? invFuelType;
  final String? invOrderNumber;
  final String? invClientId;
  final String? invClientName;
  final String? invDriverName;

  factory Trip.fromJson(Map<String, dynamic> json) => Trip(
        id: json['id'] as String,
        orderId: json['order_id'] as String,
        driverId: json['driver_id'] as String,
        vehicleId: json['vehicle_id'] as String?,
        status: TripStatus.fromString(json['status'] as String),
        volumePlanned:
            (json['volume_planned'] as num).toDouble(),
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
        driverNotes: json['driver_notes'] as String?,
        isArchived: (json['is_archived'] ?? false) as bool,
        createdAt:
            DateTime.parse(json['created_at'] as String),
        updatedAt:
            DateTime.parse(json['updated_at'] as String),
        invFuelType: json['inv_fuel_type'] as String?,
        invOrderNumber: json['inv_order_number'] as String?,
        invClientId: json['inv_client_id'] as String?,
        invClientName: json['inv_client_name'] as String?,
        invDriverName: json['inv_driver_name'] as String?,
      );
}

// ---------------------------------------------------------------------------
// Repository
// ---------------------------------------------------------------------------

class TripsRepository {
  TripsRepository._();
  static final TripsRepository instance = TripsRepository._();

  Dio get _dio => ApiClient.instance.dio;
  String get _base => AppConfig.deliveryBase;

  /// List trips. [status] = null means all statuses.
  Future<List<Trip>> list({
    TripStatus? status,
    String? driverId,
    int offset = 0,
    int limit = 100,
  }) async {
    final params = <String, dynamic>{
      'offset': offset,
      'limit': limit,
    };
    if (status != null) params['status'] = status.toApiString();
    if (driverId != null) params['driver_id'] = driverId;
    final resp = await _dio.get(
      '$_base/trips',
      queryParameters: params,
    );
    return (resp.data as List)
        .map((e) => Trip.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// Driver: complete an in-transit trip with actual volume.
  Future<Trip> complete(
    String tripId, {
    required double volumeActual,
    String? driverNotes,
  }) async {
    final resp = await _dio.post(
      '$_base/trips/$tripId/complete',
      data: {
        'volume_actual': volumeActual,
        if (driverNotes != null && driverNotes.isNotEmpty)
          'driver_notes': driverNotes,
      },
    );
    return Trip.fromJson(resp.data as Map<String, dynamic>);
  }

  /// Manager/admin: cancel an in-transit trip.
  Future<Trip> cancel(String tripId) async {
    final resp =
        await _dio.post('$_base/trips/$tripId/cancel', data: <String, dynamic>{});
    return Trip.fromJson(resp.data as Map<String, dynamic>);
  }
}
