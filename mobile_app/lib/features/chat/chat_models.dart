/// Модели чата — поля соответствуют схемам chat_service.

class ChatMessage {
  ChatMessage({
    required this.id,
    required this.conversationId,
    required this.senderId,
    required this.senderRole,
    required this.senderName,
    required this.msgType,
    required this.text,
    required this.createdAt,
    this.metadata,
    this.replyToId,
    this.isPinned = false,
    this.replyPreview,
  });

  final String id;
  final String conversationId;
  final String senderId;
  final String senderRole;
  final String senderName;

  /// text | photo | video | document
  final String msgType;
  final String text;
  final DateTime createdAt;

  /// Для photo/video: {path, mime, size, original_name}
  final Map<String, dynamic>? metadata;

  // Ответ + закреп (правки 2026-06-24)
  final String? replyToId;
  final bool isPinned;
  final ReplyPreview? replyPreview;

  bool get isPhoto => msgType == 'photo';
  bool get isVideo => msgType == 'video';
  bool get isDocument => msgType == 'document';
  bool get isText => msgType == 'text';

  factory ChatMessage.fromJson(Map<String, dynamic> json) => ChatMessage(
    id: json['id'] as String,
    conversationId: json['conversation_id'] as String,
    senderId: json['sender_id'] as String,
    senderRole: json['sender_role'] as String,
    senderName: json['sender_name'] as String,
    msgType: (json['msg_type'] ?? 'text') as String,
    text: (json['text'] ?? '') as String,
    createdAt: DateTime.parse(json['created_at'] as String),
    metadata: json['metadata'] as Map<String, dynamic>?,
    replyToId: json['reply_to_id']?.toString(),
    isPinned: (json['is_pinned'] ?? false) as bool,
    replyPreview: json['reply_preview'] == null
        ? null
        : ReplyPreview.fromJson(json['reply_preview'] as Map<String, dynamic>),
  );

  /// Строит URL вложения для скачивания через бэк.
  String attachmentUrl(String chatBase) {
    final path = metadata?['path'] as String?;
    if (path == null) return '';
    return '$chatBase/conversations/$conversationId/attachments/$path';
  }
}

/// Снимок родительского сообщения для отрисовки «ответа» (ReplyPreview).
class ReplyPreview {
  ReplyPreview({
    required this.id,
    required this.senderName,
    required this.text,
  });

  final String id;
  final String senderName;
  final String text;

  factory ReplyPreview.fromJson(Map<String, dynamic> json) => ReplyPreview(
    id: (json['id'] as Object).toString(),
    senderName: (json['sender_name'] ?? '') as String,
    text: (json['text'] ?? '') as String,
  );
}

class Conversation {
  Conversation({
    required this.id,
    required this.kind,
    required this.createdById,
    required this.createdByRole,
    required this.unreadCount,
    required this.updatedAt,
    required this.isPinned,
    this.title,
    this.clientId,
    this.driverId,
    this.orderId,
    this.groupCode,
    this.lastMessage,
    this.peerName,
    this.peerPhone,
  });

  final String id;
  final String kind;
  final String? title;
  final String? clientId;
  final String? driverId;
  final String? orderId;
  final String? groupCode;
  final String createdById;
  final String createdByRole;
  final int unreadCount;
  final ChatMessage? lastMessage;
  final DateTime updatedAt;
  final String? peerName;
  final String? peerPhone;
  final bool isPinned;

  /// Человекочитаемое название диалога (fallback: kind).
  String get displayTitle {
    if (title != null && title!.isNotEmpty) return title!;
    if (peerName != null && peerName!.isNotEmpty) return peerName!;
    switch (kind) {
      case 'direct':
        return peerPhone ?? 'Прямой чат';
      case 'client_manager':
        return 'Чат с менеджером';
      case 'client_accountant':
        return 'Чат с бухгалтером';
      default:
        return kind;
    }
  }

  factory Conversation.fromJson(Map<String, dynamic> json) {
    final lm = json['last_message'];
    return Conversation(
      id: json['id'] as String,
      kind: json['kind'] as String,
      title: json['title'] as String?,
      clientId: json['client_id'] as String?,
      driverId: json['driver_id'] as String?,
      orderId: json['order_id'] as String?,
      groupCode: json['group_code'] as String?,
      createdById: json['created_by_id'] as String,
      createdByRole: json['created_by_role'] as String,
      unreadCount: (json['unread_count'] ?? 0) as int,
      lastMessage: lm != null
          ? ChatMessage.fromJson(lm as Map<String, dynamic>)
          : null,
      updatedAt: DateTime.parse(json['updated_at'] as String),
      peerName: json['peer_name'] as String?,
      peerPhone: json['peer_phone'] as String?,
      isPinned: (json['is_pinned'] ?? false) as bool,
    );
  }
}
