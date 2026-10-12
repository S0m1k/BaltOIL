import 'package:dio/dio.dart';

import '../../core/api_client.dart';
import '../../core/app_config.dart';

class ClientItem {
  const ClientItem({
    required this.id,
    required this.fullName,
    this.email,
    this.phone,
    this.isActive = true,
    this.clientNumber,
    this.isOneOff = false,
  });

  final String id;
  final String fullName;
  final String? email;
  final String? phone;
  final bool isActive;
  final int? clientNumber;

  /// Разовый клиент (правки 2026-07-11) — создан из формы заявки.
  final bool isOneOff;

  factory ClientItem.fromJson(Map<String, dynamic> json) => ClientItem(
        id: (json['id'] as Object).toString(),
        fullName: (json['full_name'] ?? '') as String,
        email: json['email'] as String?,
        phone: json['phone'] as String?,
        isActive: (json['is_active'] ?? true) as bool,
        clientNumber: json['client_number'] as int?,
        isOneOff: (json['is_one_off'] ?? false) as bool,
      );
}

class ClientDetail {
  const ClientDetail({
    required this.id,
    required this.fullName,
    this.email,
    this.phone,
    this.isActive = true,
    this.clientNumber,
    this.profile,
  });

  final String id;
  final String fullName;
  final String? email;
  final String? phone;
  final bool isActive;
  final int? clientNumber;
  final ClientProfile? profile;

  factory ClientDetail.fromJson(Map<String, dynamic> json) {
    ClientProfile? profile;
    final raw = json['client_profile'];
    if (raw is Map<String, dynamic>) {
      profile = ClientProfile.fromJson(raw);
    }
    return ClientDetail(
      id: (json['id'] as Object).toString(),
      fullName: (json['full_name'] ?? '') as String,
      email: json['email'] as String?,
      phone: json['phone'] as String?,
      isActive: (json['is_active'] ?? true) as bool,
      clientNumber: json['client_number'] as int?,
      profile: profile,
    );
  }
}

class ClientProfile {
  const ClientProfile({
    this.clientType,
    this.companyName,
    this.inn,
    this.kpp,
    this.ogrn,
    this.legalAddress,
    this.deliveryAddress,
    this.bankName,
    this.bankAccount,
    this.billingEmail,
    this.creditAllowed = false,
    this.creditLimit,
    this.tariffId,
    this.messengerBlocked = false,
    this.chatsOnly = false,
  });

  final String? clientType; // 'individual' | 'company'
  final String? companyName;
  final String? inn;
  final String? kpp;
  final String? ogrn;
  final String? legalAddress;
  final String? deliveryAddress;
  final String? bankName;
  final String? bankAccount;
  final String? billingEmail;
  final bool creditAllowed;
  final double? creditLimit;
  final String? tariffId;
  final bool messengerBlocked;
  final bool chatsOnly;

  factory ClientProfile.fromJson(Map<String, dynamic> json) => ClientProfile(
        clientType: json['client_type'] as String?,
        companyName: json['company_name'] as String?,
        inn: json['inn'] as String?,
        kpp: json['kpp'] as String?,
        ogrn: json['ogrn'] as String?,
        legalAddress: json['legal_address'] as String?,
        deliveryAddress: json['delivery_address'] as String?,
        bankName: json['bank_name'] as String?,
        bankAccount: json['bank_account'] as String?,
        billingEmail: json['billing_email'] as String?,
        creditAllowed: (json['credit_allowed'] ?? false) as bool,
        creditLimit: (json['credit_limit'] as num?)?.toDouble(),
        tariffId: json['tariff_id']?.toString(),
        messengerBlocked: (json['messenger_blocked'] ?? false) as bool,
        chatsOnly: (json['chats_only'] ?? false) as bool,
      );
}

class ClientsRepository {
  ClientsRepository._();
  static final ClientsRepository instance = ClientsRepository._();

  Dio get _dio => ApiClient.instance.dio;
  String get _base => AppConfig.authBase;

  Future<List<ClientItem>> list({
    bool includeInactive = false,
    bool? oneOff, // true — только разовые, false — только обычные
    int offset = 0,
    int limit = 100,
  }) async {
    final resp = await _dio.get(
      '$_base/users',
      queryParameters: {
        'role': 'client',
        'include_inactive': includeInactive,
        if (oneOff != null) 'one_off': oneOff,
        'offset': offset,
        'limit': limit,
      },
    );
    return (resp.data as List)
        .map((e) => ClientItem.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// Дата последней доставки по клиентам: {client_id: ISO-дата}
  /// (GET /orders/last-delivery-by-client, staff). Ошибка не критична —
  /// список клиентов показывается без дат.
  Future<Map<String, DateTime>> lastDeliveryByClient() async {
    final resp =
        await _dio.get('${AppConfig.orderBase}/orders/last-delivery-by-client');
    final raw = resp.data as Map<String, dynamic>;
    return {
      for (final e in raw.entries)
        if (DateTime.tryParse(e.value.toString()) != null)
          e.key: DateTime.parse(e.value.toString()),
    };
  }

  Future<ClientDetail> getDetail(String userId) async {
    final resp = await _dio.get('$_base/users/$userId');
    return ClientDetail.fromJson(resp.data as Map<String, dynamic>);
  }

  /// Настройки клиента staff'ом (веб promptClientSettings):
  /// тариф, «В долг», ВЫКЛ мессенджер, «Только чаты» (правки 2026-07-14).
  Future<void> updateSettings(
    String userId, {
    String? tariffId,
    required bool creditAllowed,
    required bool messengerBlocked,
    required bool chatsOnly,
  }) async {
    await _dio.patch(
      '$_base/users/$userId/tariff',
      data: {
        'tariff_id': tariffId,
        'credit_allowed': creditAllowed,
        'messenger_blocked': messengerBlocked,
        'chats_only': chatsOnly,
      },
    );
  }
}
