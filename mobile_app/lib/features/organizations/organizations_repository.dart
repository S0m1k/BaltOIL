import 'package:dio/dio.dart';

import '../../core/api_client.dart';
import '../../core/app_config.dart';

/// Организация (юрлицо) — поля соответствуют OrganizationResponse auth_service.
class Organization {
  const Organization({
    required this.id,
    required this.orgNumber,
    required this.companyName,
    this.inn,
    this.kpp,
    this.ogrn,
    this.legalAddress,
    this.deliveryAddress,
    this.bankName,
    this.bik,
    this.bankAccount,
    this.correspondentAccount,
    this.contractNumber,
    this.billingEmail,
    this.fnsStatus,
    this.directorName,
    this.creditAllowed = false,
  });

  final String id;
  final int orgNumber;
  final String companyName;
  final String? inn;
  final String? kpp;
  final String? ogrn;
  final String? legalAddress;
  final String? deliveryAddress;
  final String? bankName;
  final String? bik;
  final String? bankAccount;
  final String? correspondentAccount;
  final String? contractNumber;
  final String? billingEmail;
  final String? fnsStatus;
  final String? directorName;
  final bool creditAllowed;

  factory Organization.fromJson(Map<String, dynamic> json) => Organization(
        id: (json['id'] as Object).toString(),
        orgNumber: (json['org_number'] ?? 0) as int,
        companyName: (json['company_name'] ?? '') as String,
        inn: json['inn'] as String?,
        kpp: json['kpp'] as String?,
        ogrn: json['ogrn'] as String?,
        legalAddress: json['legal_address'] as String?,
        deliveryAddress: json['delivery_address'] as String?,
        bankName: json['bank_name'] as String?,
        bik: json['bik'] as String?,
        bankAccount: json['bank_account'] as String?,
        correspondentAccount: json['correspondent_account'] as String?,
        contractNumber: json['contract_number'] as String?,
        billingEmail: json['billing_email'] as String?,
        fnsStatus: json['fns_status'] as String?,
        directorName: json['director_name'] as String?,
        creditAllowed: (json['credit_allowed'] ?? false) as bool,
      );
}

/// Участник организации (OrganizationMemberResponse).
class OrganizationMember {
  const OrganizationMember({
    required this.id,
    this.userId,
    this.memberRole,
    this.status,
    this.fullName,
    this.phone,
    this.invitePhone,
  });

  final String id;
  final String? userId;
  final String? memberRole; // owner | member
  final String? status;
  final String? fullName;
  final String? phone;
  final String? invitePhone;

  factory OrganizationMember.fromJson(Map<String, dynamic> json) =>
      OrganizationMember(
        id: (json['id'] as Object).toString(),
        userId: json['user_id']?.toString(),
        memberRole: json['member_role'] as String?,
        status: json['status'] as String?,
        fullName: json['full_name'] as String?,
        phone: json['phone'] as String?,
        invitePhone: json['invite_phone'] as String?,
      );
}

class OrganizationsRepository {
  OrganizationsRepository._();
  static final OrganizationsRepository instance = OrganizationsRepository._();

  Dio get _dio => ApiClient.instance.dio;
  String get _base => AppConfig.authBase;

  /// Staff без user_id — все организации (поиск по названию/ИНН);
  /// клиент — только свои. Роль разруливает сервер.
  Future<List<Organization>> list({String? search}) async {
    final resp = await _dio.get(
      '$_base/organizations',
      queryParameters: {
        if (search != null && search.isNotEmpty) 'search': search,
      },
    );
    return (resp.data as List)
        .map((e) => Organization.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<Organization> get(String orgId) async {
    final resp = await _dio.get('$_base/organizations/$orgId');
    return Organization.fromJson(resp.data as Map<String, dynamic>);
  }

  Future<List<OrganizationMember>> members(String orgId) async {
    final resp = await _dio.get('$_base/organizations/$orgId/members');
    return (resp.data as List)
        .map((e) => OrganizationMember.fromJson(e as Map<String, dynamic>))
        .toList();
  }
}
