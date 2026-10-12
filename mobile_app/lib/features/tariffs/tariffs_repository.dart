import 'package:dio/dio.dart';

import '../../core/api_client.dart';
import '../../core/app_config.dart';

// ---------------------------------------------------------------------------
// Models
// ---------------------------------------------------------------------------

class TariffFuelPrice {
  TariffFuelPrice({
    required this.id,
    required this.fuelType,
    required this.pricePerLiter,
  });

  final String id;
  final String fuelType;
  final double pricePerLiter;

  factory TariffFuelPrice.fromJson(Map<String, dynamic> json) =>
      TariffFuelPrice(
        id: json['id'] as String,
        fuelType: json['fuel_type'] as String,
        pricePerLiter: double.parse(json['price_per_liter'].toString()),
      );

  Map<String, dynamic> toJson() => {
        'fuel_type': fuelType,
        'price_per_liter': pricePerLiter,
      };
}

class TariffVolumeTier {
  TariffVolumeTier({
    required this.id,
    required this.minVolume,
    required this.discountPct,
  });

  final String id;
  final double minVolume;
  final double discountPct;

  factory TariffVolumeTier.fromJson(Map<String, dynamic> json) =>
      TariffVolumeTier(
        id: json['id'] as String,
        minVolume: double.parse(json['min_volume'].toString()),
        discountPct: double.parse(json['discount_pct'].toString()),
      );

  Map<String, dynamic> toJson() => {
        'min_volume': minVolume,
        'discount_pct': discountPct,
      };
}

class Tariff {
  Tariff({
    required this.id,
    required this.name,
    required this.isDefault,
    required this.isArchived,
    required this.baseDeliveryCost,
    required this.fuelPrices,
    required this.volumeTiers,
    this.description,
    this.clientType,
  });

  final String id;
  final String name;
  final bool isDefault;
  final bool isArchived;
  final double baseDeliveryCost;
  final List<TariffFuelPrice> fuelPrices;
  final List<TariffVolumeTier> volumeTiers;
  final String? description;
  final String? clientType;

  factory Tariff.fromJson(Map<String, dynamic> json) => Tariff(
        id: json['id'] as String,
        name: json['name'] as String,
        isDefault: (json['is_default'] ?? false) as bool,
        isArchived: (json['is_archived'] ?? false) as bool,
        baseDeliveryCost:
            double.parse((json['base_delivery_cost'] ?? '0').toString()),
        description: json['description'] as String?,
        clientType: json['client_type'] as String?,
        fuelPrices: (json['fuel_prices'] as List)
            .map((e) => TariffFuelPrice.fromJson(e as Map<String, dynamic>))
            .toList(),
        volumeTiers: (json['volume_tiers'] as List)
            .map((e) => TariffVolumeTier.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

// Input for create / update
class TariffInput {
  TariffInput({
    required this.name,
    required this.fuelPrices,
    this.description,
    this.volumeTiers = const [],
    this.clientType,
    this.baseDeliveryCost = 0.0,
  });

  final String name;
  final String? description;
  final List<TariffFuelPrice> fuelPrices;
  final List<TariffVolumeTier> volumeTiers;
  final String? clientType;
  final double baseDeliveryCost;

  Map<String, dynamic> toJson() => {
        'name': name,
        if (description != null) 'description': description,
        'fuel_prices': fuelPrices.map((f) => f.toJson()).toList(),
        'volume_tiers': volumeTiers.map((t) => t.toJson()).toList(),
        if (clientType != null) 'client_type': clientType,
        'base_delivery_cost': baseDeliveryCost,
      };
}

// ---------------------------------------------------------------------------
// Repository
// ---------------------------------------------------------------------------

class TariffsRepository {
  TariffsRepository._();
  static final TariffsRepository instance = TariffsRepository._();

  Dio get _dio => ApiClient.instance.dio;
  String get _base => AppConfig.orderBase;

  /// GET /tariffs  — list all (optionally including archived).
  /// GET /tariffs/defaults — базовые тарифы по типам клиентов,
  /// доступен любому авторизованному, включая водителей (веб 435d822).
  Future<List<Tariff>> defaults() async {
    final resp = await _dio.get('$_base/tariffs/defaults');
    return (resp.data as List)
        .map((e) => Tariff.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<List<Tariff>> list({bool includeArchived = false}) async {
    final resp = await _dio.get(
      '$_base/tariffs',
      queryParameters: {'include_archived': includeArchived},
    );
    return (resp.data as List)
        .map((e) => Tariff.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// GET /tariffs/default
  Future<Tariff> getDefault() async {
    final resp = await _dio.get('$_base/tariffs/default');
    return Tariff.fromJson(resp.data as Map<String, dynamic>);
  }

  /// GET /tariffs/{id}
  Future<Tariff> getById(String tariffId) async {
    final resp = await _dio.get('$_base/tariffs/$tariffId');
    return Tariff.fromJson(resp.data as Map<String, dynamic>);
  }

  /// POST /tariffs  — admin only (enforced server-side).
  Future<Tariff> create(TariffInput input) async {
    final resp = await _dio.post('$_base/tariffs', data: input.toJson());
    return Tariff.fromJson(resp.data as Map<String, dynamic>);
  }

  /// PUT /tariffs/{id}  — admin only.
  Future<Tariff> update(String tariffId, TariffInput input) async {
    final resp = await _dio.put(
      '$_base/tariffs/$tariffId',
      data: input.toJson(),
    );
    return Tariff.fromJson(resp.data as Map<String, dynamic>);
  }

  /// POST /tariffs/{id}/set-default  — admin only.
  Future<Tariff> setDefault(String tariffId) async {
    final resp =
        await _dio.post('$_base/tariffs/$tariffId/set-default', data: {});
    return Tariff.fromJson(resp.data as Map<String, dynamic>);
  }

  /// POST /tariffs/{id}/archive  — admin only.
  Future<Tariff> archive(String tariffId) async {
    final resp =
        await _dio.post('$_base/tariffs/$tariffId/archive', data: {});
    return Tariff.fromJson(resp.data as Map<String, dynamic>);
  }
}
