import 'package:dio/dio.dart';

import '../../core/api_client.dart';
import '../../core/app_config.dart';

/// Звонок (CallResponse call_service). Статусы: ringing | active | ended | missed.
class CallInfo {
  CallInfo({
    required this.id,
    required this.conversationId,
    required this.roomName,
    required this.status,
    required this.initiatedById,
    required this.initiatedByName,
  });

  final String id;
  final String conversationId;
  final String roomName;
  final String status;
  final String initiatedById;
  final String initiatedByName;

  factory CallInfo.fromJson(Map<String, dynamic> json) => CallInfo(
        id: (json['id'] as Object).toString(),
        conversationId: (json['conversation_id'] as Object).toString(),
        roomName: json['room_name'] as String,
        status: (json['status'] ?? '') as String,
        initiatedById: (json['initiated_by_id'] as Object).toString(),
        initiatedByName: (json['initiated_by_name'] ?? '') as String,
      );
}

/// Токен для входа в комнату LiveKit (TokenResponse call_service).
class CallToken {
  CallToken({
    required this.callId,
    required this.roomName,
    required this.token,
    required this.livekitUrl,
  });

  final String callId;
  final String roomName;
  final String token;
  final String livekitUrl;

  factory CallToken.fromJson(Map<String, dynamic> json) => CallToken(
        callId: (json['call_id'] as Object).toString(),
        roomName: json['room_name'] as String,
        token: json['token'] as String,
        livekitUrl: json['livekit_url'] as String,
      );
}

/// Клиент call_service (порт 8006, маршруты без /api/v1 — как CALL_URL веба).
class CallRepository {
  CallRepository._();
  static final CallRepository instance = CallRepository._();

  Dio get _dio => ApiClient.instance.dio;
  String get _base => AppConfig.callBase;

  /// Инициировать звонок в диалоге. Сервер создаёт комнату LiveKit,
  /// рассылает call_initiated участникам и возвращает токен инициатору.
  Future<CallToken> start(String conversationId) async {
    final resp = await _dio.post(
      '$_base/calls/start',
      data: {'conversation_id': conversationId},
    );
    return CallToken.fromJson(resp.data as Map<String, dynamic>);
  }

  /// Токен для входа в существующую комнату (ответ на звонок).
  Future<CallToken> token(String roomName) async {
    final resp = await _dio.post(
      '$_base/calls/token',
      data: {'room_name': roomName},
    );
    return CallToken.fromJson(resp.data as Map<String, dynamic>);
  }

  /// Завершить звонок (обе стороны могут).
  Future<void> end(String callId) async {
    await _dio.post('$_base/calls/$callId/end');
  }

  /// Активные звонки текущего пользователя — для поллинга входящих
  /// (веб startCallPolling, раз в несколько секунд).
  Future<List<CallInfo>> active() async {
    final resp = await _dio.get('$_base/calls/active');
    return (resp.data as List)
        .map((e) => CallInfo.fromJson(e as Map<String, dynamic>))
        .toList();
  }
}
