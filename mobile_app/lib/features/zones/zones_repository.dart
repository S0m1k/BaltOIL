import 'package:dio/dio.dart';

import '../../core/api_client.dart';
import '../../core/app_config.dart';

// ---------------------------------------------------------------------------
// Models
// ---------------------------------------------------------------------------

class DeliveryZone {
  DeliveryZone({
    required this.id,
    required this.name,
    required this.polygon,
    required this.costCoefficient,
    required this.isActive,
    this.deliveryPrice,
  });

  final String id;
  final String name;

  /// Список координатных пар [[lat, lng], ...] — формат Leaflet/бэка.
  final List<List<double>> polygon;

  final double costCoefficient;

  /// Фиксированная стоимость доставки, ₽. null → расчёт по коэффициенту.
  final double? deliveryPrice;

  final bool isActive;

  factory DeliveryZone.fromJson(Map<String, dynamic> json) {
    final rawPolygon = (json['polygon'] as List? ?? []);
    final polygon = rawPolygon.map((point) {
      final p = point as List;
      return [
        double.parse(p[0].toString()),
        double.parse(p[1].toString()),
      ];
    }).toList();

    return DeliveryZone(
      id: json['id'] as String,
      name: json['name'] as String,
      polygon: polygon,
      costCoefficient:
          double.parse((json['cost_coefficient'] ?? '1.0').toString()),
      deliveryPrice: json['delivery_price'] != null
          ? double.parse(json['delivery_price'].toString())
          : null,
      isActive: (json['is_active'] ?? true) as bool,
    );
  }
}

class ZoneCreateInput {
  ZoneCreateInput({
    required this.name,
    required this.deliveryPrice,
    this.polygon = const [],
    this.costCoefficient = 1.0,
    this.isActive = true,
  });

  final String name;
  final double deliveryPrice;
  final List<List<double>> polygon;
  final double costCoefficient;
  final bool isActive;

  Map<String, dynamic> toJson() => {
        'name': name,
        'delivery_price': deliveryPrice,
        // Бэк требует минимум 3 точки; при создании через мобильный UI
        // полигон не рисуется — передаём три заглушечные точки (0,0),
        // которые можно заменить позже через веб-интерфейс.
        // TODO: добавить рисование полигона через flutter_map + geofence (десктопная задача).
        'polygon': polygon.isEmpty
            ? [
                [0.0, 0.0],
                [0.0, 0.001],
                [0.001, 0.0],
              ]
            : polygon,
        'cost_coefficient': costCoefficient,
        'is_active': isActive,
      };
}

class ZoneUpdateInput {
  ZoneUpdateInput({this.name, this.deliveryPrice});

  final String? name;
  final double? deliveryPrice;

  Map<String, dynamic> toJson() => {
        if (name != null) 'name': name,
        if (deliveryPrice != null) 'delivery_price': deliveryPrice,
      };
}

// ---------------------------------------------------------------------------
// Repository
// ---------------------------------------------------------------------------

class ZonesRepository {
  ZonesRepository._();
  static final ZonesRepository instance = ZonesRepository._();

  Dio get _dio => ApiClient.instance.dio;
  String get _base => AppConfig.deliveryBase;

  /// GET /zones — список активных зон (любой авторизованный).
  Future<List<DeliveryZone>> listActive() async {
    final resp = await _dio.get('$_base/zones');
    return (resp.data as List)
        .map((e) => DeliveryZone.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// POST /zones — создать зону (admin only, enforcement on server).
  Future<DeliveryZone> create(ZoneCreateInput input) async {
    final resp = await _dio.post('$_base/zones', data: input.toJson());
    return DeliveryZone.fromJson(resp.data as Map<String, dynamic>);
  }

  /// PUT /zones/{id} — обновить зону (admin only).
  Future<DeliveryZone> update(String zoneId, ZoneUpdateInput input) async {
    final resp =
        await _dio.put('$_base/zones/$zoneId', data: input.toJson());
    return DeliveryZone.fromJson(resp.data as Map<String, dynamic>);
  }

  /// DELETE /zones/{id} — мягкое удаление (admin only).
  Future<void> delete(String zoneId) async {
    await _dio.delete('$_base/zones/$zoneId');
  }
}
