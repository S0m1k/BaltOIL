import 'package:dio/dio.dart';

import '../../core/api_client.dart';
import '../../core/app_config.dart';

class AppNotification {
  AppNotification({
    required this.id,
    required this.type,
    required this.title,
    required this.body,
    required this.isRead,
    this.entityId,
    this.createdAt,
  });

  final String id;
  final String type;
  final String title;
  final String body;
  final bool isRead;
  final String? entityId; // chat_message → conversation_id
  final DateTime? createdAt;

  factory AppNotification.fromJson(Map<String, dynamic> json) =>
      AppNotification(
        id: json['id'] as String,
        type: json['type'] as String,
        title: json['title'] as String,
        body: json['body'] as String,
        isRead: (json['is_read'] ?? false) as bool,
        entityId: json['entity_id']?.toString(),
        createdAt: json['created_at'] == null
            ? null
            : DateTime.tryParse(json['created_at'] as String),
      );
}

class NotificationsRepository {
  NotificationsRepository._();
  static final NotificationsRepository instance = NotificationsRepository._();

  Dio get _dio => ApiClient.instance.dio;
  String get _base => AppConfig.notificationBase;

  Future<List<AppNotification>> list({int limit = 30}) async {
    final resp = await _dio
        .get('$_base/notifications', queryParameters: {'limit': limit});
    return (resp.data as List)
        .map((e) => AppNotification.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// Число непрочитанных для badge на вкладке (как .notif-count на вебе).
  Future<int> unreadCount() async {
    final resp = await _dio.get('$_base/notifications',
        queryParameters: {'unread_only': true, 'limit': 20});
    return (resp.data as List).length;
  }

  Future<void> markRead(String id) =>
      _dio.post('$_base/notifications/$id/read');

  Future<void> markAllRead() => _dio.post('$_base/notifications/read-all');
}
