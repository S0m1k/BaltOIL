import 'package:dio/dio.dart';

import '../../core/api_client.dart';
import '../../core/app_config.dart';

/// Реквизиты юридического лица (продавца — БалтОйл).
///
/// Каждое сохранение создаёт новую версию; предыдущая архивируется.
/// Доступ только для роли admin.
class SellerLegalEntity {
  const SellerLegalEntity({
    required this.id,
    required this.name,
    this.shortName,
    required this.inn,
    this.kpp,
    this.ogrn,
    this.okpo,
    this.bankName,
    this.bik,
    this.checkingAccount,
    this.correspondentAccount,
    this.legalAddress,
    this.actualAddress,
    this.phone,
    this.email,
    this.directorName,
    this.directorTitle,
    required this.vatRate,
    required this.effectiveFrom,
    this.effectiveTo,
    required this.isActive,
    required this.createdAt,
  });

  final String id;

  // Юридическое лицо
  final String name;
  final String? shortName;
  final String inn;
  final String? kpp;
  final String? ogrn;
  final String? okpo;

  // Банковские реквизиты
  final String? bankName;
  final String? bik;
  final String? checkingAccount;      // р/с (checking_account)
  final String? correspondentAccount; // к/с (correspondent_account)

  // Адреса и контакты
  final String? legalAddress;
  final String? actualAddress;
  final String? phone;
  final String? email;

  // Подписант
  final String? directorName;
  final String? directorTitle;

  // Налогообложение
  final int vatRate;

  // История версий
  final DateTime effectiveFrom;
  final DateTime? effectiveTo;
  final bool isActive;
  final DateTime createdAt;

  factory SellerLegalEntity.fromJson(Map<String, dynamic> json) {
    return SellerLegalEntity(
      id: json['id'] as String,
      name: json['name'] as String,
      shortName: json['short_name'] as String?,
      inn: json['inn'] as String,
      kpp: json['kpp'] as String?,
      ogrn: json['ogrn'] as String?,
      okpo: json['okpo'] as String?,
      bankName: json['bank_name'] as String?,
      bik: json['bik'] as String?,
      checkingAccount: json['checking_account'] as String?,
      correspondentAccount: json['correspondent_account'] as String?,
      legalAddress: json['legal_address'] as String?,
      actualAddress: json['actual_address'] as String?,
      phone: json['phone'] as String?,
      email: json['email'] as String?,
      directorName: json['director_name'] as String?,
      directorTitle: json['director_title'] as String?,
      vatRate: (json['vat_rate'] as num?)?.toInt() ?? 22,
      effectiveFrom: DateTime.parse(json['effective_from'] as String),
      effectiveTo: json['effective_to'] != null
          ? DateTime.parse(json['effective_to'] as String)
          : null,
      isActive: json['is_active'] as bool? ?? true,
      createdAt: DateTime.parse(json['created_at'] as String),
    );
  }
}

/// Репозиторий реквизитов продавца (order_service /admin/legal-entity).
///
/// GET  /admin/legal-entity          → текущая (активная) версия или null
/// PUT  /admin/legal-entity          → сохранить новую версию (архивирует текущую)
/// GET  /admin/legal-entity/history  → список всех версий
class RequisitesRepository {
  RequisitesRepository._();
  static final RequisitesRepository instance = RequisitesRepository._();

  Dio get _dio => ApiClient.instance.dio;
  String get _base => '${AppConfig.orderBase}/admin/legal-entity';

  /// Получить активные реквизиты. Возвращает null, если ни одной версии нет.
  Future<SellerLegalEntity?> getCurrent() async {
    final resp = await _dio.get(_base);
    if (resp.data == null) return null;
    return SellerLegalEntity.fromJson(resp.data as Map<String, dynamic>);
  }

  /// Создать новую версию реквизитов (текущая автоматически архивируется бэком).
  Future<SellerLegalEntity> save(Map<String, dynamic> payload) async {
    final resp = await _dio.put(_base, data: payload);
    return SellerLegalEntity.fromJson(resp.data as Map<String, dynamic>);
  }

  /// История всех версий (от новых к старым).
  Future<List<SellerLegalEntity>> getHistory() async {
    final resp = await _dio.get('$_base/history');
    return (resp.data as List)
        .map((e) => SellerLegalEntity.fromJson(e as Map<String, dynamic>))
        .toList();
  }
}
