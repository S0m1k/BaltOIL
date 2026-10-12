import 'package:dio/dio.dart';

import '../../core/api_client.dart';
import '../../core/app_config.dart';

class UserItem {
  const UserItem({
    required this.id,
    required this.fullName,
    required this.role,
    this.email,
    this.phone,
    this.isActive = true,
    this.clientNumber,
  });

  final String id;
  final String fullName;
  final String role; // admin | manager | driver | client
  final String? email;
  final String? phone;
  final bool isActive;
  final int? clientNumber;

  factory UserItem.fromJson(Map<String, dynamic> json) => UserItem(
        id: (json['id'] as Object).toString(),
        fullName: (json['full_name'] ?? '') as String,
        role: (json['role'] ?? '') as String,
        email: json['email'] as String?,
        phone: json['phone'] as String?,
        isActive: (json['is_active'] ?? true) as bool,
        clientNumber: json['client_number'] as int?,
      );
}

class CreateUserPayload {
  const CreateUserPayload({
    required this.fullName,
    required this.role,
    required this.password,
    this.email,
    this.phone,
  });

  final String fullName;
  final String role;
  final String password;
  final String? email;
  final String? phone;
}

class UsersRepository {
  UsersRepository._();
  static final UsersRepository instance = UsersRepository._();

  Dio get _dio => ApiClient.instance.dio;
  String get _base => AppConfig.authBase;

  Future<List<UserItem>> list({
    String? role,
    bool includeInactive = false,
    int offset = 0,
    int limit = 100,
  }) async {
    final resp = await _dio.get(
      '$_base/users',
      queryParameters: {
        'include_inactive': includeInactive,
        'offset': offset,
        'limit': limit,
        if (role != null) 'role': role,
      },
    );
    return (resp.data as List)
        .map((e) => UserItem.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// Admin only — POST /users
  Future<UserItem> createUser(CreateUserPayload payload) async {
    final resp = await _dio.post(
      '$_base/users',
      data: {
        'full_name': payload.fullName,
        'role': payload.role,
        'password': payload.password,
        if (payload.email != null && payload.email!.isNotEmpty)
          'email': payload.email,
        if (payload.phone != null && payload.phone!.isNotEmpty)
          'phone': payload.phone,
      },
    );
    return UserItem.fromJson(resp.data as Map<String, dynamic>);
  }
}
