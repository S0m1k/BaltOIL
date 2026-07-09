import 'package:dio/dio.dart';

import '../../core/api_client.dart';
import '../../core/app_config.dart';

/// Договор поставки (ContractResponse order_service).
class Contract {
  const Contract({
    required this.id,
    required this.contractNumber,
    required this.status,
    this.signedAt,
    this.createdAt,
    this.organizationName,
  });

  final String id;
  final String contractNumber;
  final String status;
  final DateTime? signedAt;
  final DateTime? createdAt;
  final String? organizationName; // только в реестре

  factory Contract.fromJson(Map<String, dynamic> json) => Contract(
    id: (json['id'] as Object).toString(),
    contractNumber: (json['contract_number'] ?? '') as String,
    status: (json['status'] ?? '') as String,
    signedAt: json['signed_at'] == null
        ? null
        : DateTime.tryParse(json['signed_at'] as String),
    createdAt: json['created_at'] == null
        ? null
        : DateTime.tryParse(json['created_at'] as String),
    organizationName: json['organization_name'] as String?,
  );
}

class ContractsRepository {
  ContractsRepository._();
  static final ContractsRepository instance = ContractsRepository._();

  Dio get _dio => ApiClient.instance.dio;
  String get _base => AppConfig.orderBase;

  /// Договор организации (веб openOrgContract): находит активный,
  /// иначе бэкенд формирует новый.
  Future<Contract> byOrganization(String orgId) async {
    final resp = await _dio.get('$_base/organizations/$orgId/contract');
    return Contract.fromJson(resp.data as Map<String, dynamic>);
  }

  /// Реестр договоров (staff, веб openContractsRegistry).
  Future<List<Contract>> registry() async {
    final resp = await _dio.get('$_base/contracts');
    return (resp.data as List)
        .map((e) => Contract.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// Перевыпуск с правкой номера/даты (staff, веб regenContract).
  Future<void> regenerate(
    String contractId, {
    String? contractNumber,
    String? signedAt,
  }) async {
    await _dio.patch(
      '$_base/contracts/$contractId/regenerate',
      data: {'contract_number': contractNumber, 'signed_at': signedAt},
    );
  }

  /// Отправить PDF договора на почту организации (staff).
  Future<String?> sendEmail(String contractId) async {
    final resp = await _dio.post(
      '$_base/contracts/$contractId/send-email',
      data: {},
    );
    return (resp.data as Map<String, dynamic>)['to'] as String?;
  }
}
