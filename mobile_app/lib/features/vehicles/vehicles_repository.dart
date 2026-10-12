import 'package:dio/dio.dart';

import '../../core/api_client.dart';
import '../../core/app_config.dart';

/// Транспортное средство (VehicleResponse delivery_service).
class Vehicle {
  const Vehicle({
    required this.id,
    required this.plateNumber,
    required this.model,
    required this.capacityLiters,
    this.assignedDriverId,
    this.notes,
    this.isActive = true,
  });

  final String id;
  final String plateNumber;
  final String model;
  final double capacityLiters;
  final String? assignedDriverId;
  final String? notes;
  final bool isActive;

  factory Vehicle.fromJson(Map<String, dynamic> json) => Vehicle(
        id: (json['id'] as Object).toString(),
        plateNumber: (json['plate_number'] ?? '') as String,
        model: (json['model'] ?? '') as String,
        capacityLiters: (json['capacity_liters'] as num? ?? 0).toDouble(),
        assignedDriverId: json['assigned_driver_id']?.toString(),
        notes: json['notes'] as String?,
        isActive: (json['is_active'] ?? true) as bool,
      );
}

class VehiclesRepository {
  VehiclesRepository._();
  static final VehiclesRepository instance = VehiclesRepository._();

  Dio get _dio => ApiClient.instance.dio;
  String get _base => AppConfig.deliveryBase;

  Future<List<Vehicle>> list() async {
    final resp = await _dio.get(
      '$_base/vehicles',
      queryParameters: {'include_inactive': true},
    );
    return (resp.data as List)
        .map((e) => Vehicle.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<Vehicle> create({
    required String plateNumber,
    required String model,
    required double capacityLiters,
    String? notes,
  }) async {
    final resp = await _dio.post('$_base/vehicles', data: {
      'plate_number': plateNumber,
      'model': model,
      'capacity_liters': capacityLiters,
      if (notes != null && notes.isNotEmpty) 'notes': notes,
    });
    return Vehicle.fromJson(resp.data as Map<String, dynamic>);
  }

  Future<void> archive(String id) async {
    await _dio.delete('$_base/vehicles/$id');
  }
}
