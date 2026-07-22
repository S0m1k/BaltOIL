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
  Future<List<ChatMessage>> fetchHistory(
    String convId, {
    int limit = 50,
  }) async {
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

  /// Удалить сообщение (правки 2026-07-21): автор — своё, менеджер/админ —
  /// любое. Мягкое удаление на бэке; остальным участникам прилетит WS-событие
  /// message_deleted.
  Future<void> deleteMessage(String convId, String messageId) async {
    await _dio.delete('$_base/conversations/$convId/messages/$messageId');
  }

  /// Удалить диалог целиком с историей (admin only, веб doDeleteConv).
  /// Остальным участникам прилетит WS-событие conversation_deleted.
  Future<void> deleteConversation(String convId) async {
    await _dio.delete('$_base/conversations/$convId');
  }

  /// Очистить историю сообщений диалога (admin only, веб doClearConv).
  /// Остальным участникам прилетит WS-событие conversation_cleared.
  Future<void> clearConversation(String convId) async {
    await _dio.post('$_base/conversations/$convId/clear');
  }

  /// «Горизонт прочтения» собеседниками — максимальный last_read_at среди
  /// участников, кроме [myUserId]. Сообщение считается прочитанным, если оно
  /// моё и его created_at ≤ этого времени. Бэк отдаёт участников с last_read_at
  /// в GET /conversations/{id}; отдельного broadcast нет, поэтому чат опрашивает
  /// это периодически. null — никто ещё не прочитал (или данных нет).
  Future<DateTime?> othersReadHorizon(String convId, String myUserId) async {
    final resp = await _dio.get('$_base/conversations/$convId');
    final data = resp.data as Map<String, dynamic>;
    final parts = (data['participants'] as List?) ?? const [];
    DateTime? horizon;
    for (final p in parts) {
      final m = p as Map<String, dynamic>;
      if (m['user_id']?.toString() == myUserId) continue;
      final raw = m['last_read_at'] as String?;
      if (raw == null) continue;
      final ts = DateTime.tryParse(raw);
      if (ts == null) continue;
      if (horizon == null || ts.isAfter(horizon)) horizon = ts;
    }
    return horizon;
  }

  /// Отправить текстовое сообщение через REST (fallback).
  /// [replyToId] — ответ на сообщение (правки 2026-06-24, F7).
  Future<ChatMessage> sendTextRest(
    String convId,
    String text, {
    String? replyToId,
  }) async {
    final resp = await _dio.post(
      '$_base/conversations/$convId/messages',
      data: {
        'text': text,
        'msg_type': 'text',
        if (replyToId != null) 'reply_to_id': replyToId,
      },
    );
    return ChatMessage.fromJson(resp.data as Map<String, dynamic>);
  }

  /// Закреп/откреп сообщения (правки 2026-06-24).
  Future<void> pinMessage(
    String convId,
    String messageId, {
    required bool pin,
  }) async {
    await _dio.post(
      '$_base/conversations/$convId/messages/$messageId/'
      '${pin ? 'pin' : 'unpin'}',
    );
  }

  /// Приватная staff-группа (веб promptCreateStaffGroup, группа «СЗТК»):
  /// видна только выбранным участникам; создатель добавляется сам.
  Future<Conversation> createStaffGroup(
    String title,
    List<String> memberIds,
  ) async {
    final resp = await _dio.post(
      '$_base/conversations/staff-group',
      data: {'title': title, 'member_ids': memberIds},
    );
    return Conversation.fromJson(resp.data as Map<String, dynamic>);
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
      data: {'text': originalName, 'msg_type': msgType, 'metadata': meta},
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
