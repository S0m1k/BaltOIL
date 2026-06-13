import 'package:dio/dio.dart';

import '../../core/api_client.dart';
import '../../core/app_config.dart';
import 'chat_models.dart';

class ChatRepository {
  ChatRepository._();
  static final ChatRepository instance = ChatRepository._();

  Dio get _dio => ApiClient.instance.dio;
  String get _base => AppConfig.chatBase;

  Future<List<Conversation>> listConversations() async {
    final resp = await _dio.get('$_base/conversations');
    return (resp.data as List)
        .map((e) => Conversation.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// История последних [limit] сообщений. Бэк принимает limit и before_id.
  Future<List<ChatMessage>> fetchHistory(String convId,
      {int limit = 50}) async {
    final resp = await _dio.get(
      '$_base/conversations/$convId/messages',
      queryParameters: {'limit': limit},
    );
    return (resp.data as List)
        .map((e) => ChatMessage.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> markRead(String convId) async {
    await _dio.post('$_base/conversations/$convId/read');
  }

  /// Отправить текстовое сообщение через REST (fallback).
  Future<ChatMessage> sendTextRest(String convId, String text) async {
    final resp = await _dio.post(
      '$_base/conversations/$convId/messages',
      data: {'text': text, 'msg_type': 'text'},
    );
    return ChatMessage.fromJson(resp.data as Map<String, dynamic>);
  }

  /// Загрузить файл вложения, получить metadata, затем отправить сообщение.
  ///
  /// [filePath] — локальный путь к файлу.
  /// [fileName] — оригинальное имя с расширением (нужно серверу для MIME).
  /// Возвращает отправленное сообщение (приходит и по WS от бэка, но REST
  /// позволяет показать моментальный optimistic update).
  Future<ChatMessage> sendAttachment({
    required String convId,
    required String filePath,
    required String fileName,
  }) async {
    // 1. Загрузить файл
    final formData = FormData.fromMap({
      'file': await MultipartFile.fromFile(filePath, filename: fileName),
    });
    final uploadResp = await _dio.post(
      '$_base/conversations/$convId/attachments',
      data: formData,
      options: Options(receiveTimeout: const Duration(seconds: 60)),
    );
    final meta = uploadResp.data as Map<String, dynamic>;
    final msgType = meta['msg_type'] as String; // photo | video
    final originalName = meta['original_name'] as String? ?? fileName;

    // 2. Отправить сообщение с metadata вложения
    final msgResp = await _dio.post(
      '$_base/conversations/$convId/messages',
      data: {
        'text': originalName,
        'msg_type': msgType,
        'metadata': meta,
      },
    );
    return ChatMessage.fromJson(msgResp.data as Map<String, dynamic>);
  }

  /// Начать (или открыть) прямой чат по номеру телефона. Доступно всем ролям.
  Future<Conversation> startByPhone(String phone) async {
    final resp = await _dio.post(
      '$_base/conversations/start-by-phone',
      data: {'phone': phone},
    );
    return Conversation.fromJson(resp.data as Map<String, dynamic>);
  }

  /// Открыть/создать чат клиент–менеджер. Только manager/admin.
  Future<Conversation> ensureClientManager(String clientId) async {
    final resp = await _dio.post(
      '$_base/conversations/ensure-client-manager',
      data: {'client_id': clientId},
    );
    return Conversation.fromJson(resp.data as Map<String, dynamic>);
  }

  /// Открыть/создать чат клиент–бухгалтер. Клиент-юрлицо или manager/admin.
  Future<Conversation> ensureClientAccountant({String? clientId}) async {
    final resp = await _dio.post(
      '$_base/conversations/ensure-client-accountant',
      data: {if (clientId != null) 'client_id': clientId},
    );
    return Conversation.fromJson(resp.data as Map<String, dynamic>);
  }
}
