import 'dart:async';
import 'dart:io';

import 'package:dio/dio.dart' show Options, ResponseType;
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:open_filex/open_filex.dart';
import 'package:path_provider/path_provider.dart';

import '../../core/api_client.dart';
import '../../core/app_config.dart';
import '../../core/token_storage.dart';
import '../../core/ws_client.dart';
import '../auth/auth_repository.dart';
import '../calls/call_repository.dart';
import '../calls/call_screen.dart';
import '../calls/incoming_call_watcher.dart';
import 'chat_models.dart';
import 'chat_repository.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key, required this.conversation});

  final Conversation conversation;

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> with WidgetsBindingObserver {
  final _textCtrl = TextEditingController();
  final _scrollCtrl = ScrollController();
  final _picker = ImagePicker();

  late ChatWsClient _ws;
  final List<ChatMessage> _messages = [];
  bool _loading = true;
  bool _sending = false;

  // Статусы прочтения (галочки): мой id/роль — чтобы отличить исходящие и
  // показать «Удалить» менеджеру/админу; горизонт — максимальный last_read_at
  // собеседников. Realtime-событие read_receipt (2026-07-21) обновляет горизонт
  // мгновенно, таймер остаётся страховкой.
  String? _myUserId;
  String? _myRole;
  DateTime? _readHorizon;
  Timer? _readTimer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _ws = ChatWsClient(convId: widget.conversation.id);
    _ws.frames.listen(_onWsFrame);
    _init();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _ws.onAppResume();
    }
  }

  Future<void> _init() async {
    await _loadHistory();
    await _ws.connect();
    // Узнаём свой id (для «мои сообщения») и запускаем опрос прочтения.
    try {
      final me = await AuthRepository.instance.me();
      if (mounted) {
        _myUserId = me.id;
        _myRole = me.role;
      }
    } on Object {
      // Без id галочки просто не покажутся — не критично.
    }
    _refreshReadHorizon();
    _readTimer = Timer.periodic(
        const Duration(seconds: 5), (_) => _refreshReadHorizon());
  }

  /// Подтягивает last_read_at собеседников — для двойных галочек «прочитано».
  Future<void> _refreshReadHorizon() async {
    final myId = _myUserId;
    if (myId == null) return;
    try {
      final h = await ChatRepository.instance
          .othersReadHorizon(widget.conversation.id, myId);
      if (mounted && h != _readHorizon) setState(() => _readHorizon = h);
    } on Object {
      // Сеть могла моргнуть — оставляем прежний горизонт.
    }
  }

  Future<void> _loadHistory() async {
    try {
      final msgs = await ChatRepository.instance.fetchHistory(
        widget.conversation.id,
        limit: 50,
      );
      // История приходит от старых к новым — порядок уже верный для ListView
      if (mounted) {
        setState(() {
          _messages.clear();
          _messages.addAll(msgs);
          _loading = false;
        });
      }
      // Отметить прочитанными в фоне — некритично
      ChatRepository.instance
          .markRead(widget.conversation.id)
          .catchError((_) {});
    } catch (e) {
      if (mounted) {
        setState(() => _loading = false);
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
    _scrollToBottom();
  }

  void _onWsFrame(WsFrame frame) {
    if (!mounted) return;
    if (frame.isError) {
      final err = frame.error!;
      // 4401 обрабатывается самим ChatWsClient (refresh + reconnect).
      // Для прочих ошибок — показываем снекбар.
      if (!err.contains('token expired')) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(err)));
      }
      return;
    }
    final raw = frame.message!;

    // Событийные кадры (правки 2026-07-21): у них нет полей сообщения,
    // ChatMessage.fromJson на них падал бы. Обрабатываем до парсинга.
    final event = raw['event'] as String?;
    if (event != null) {
      switch (event) {
        case 'read_receipt':
          // Собеседник прочитал — двигаем горизонт, галочки синеют сразу.
          if (raw['user_id']?.toString() != _myUserId) {
            final ts = DateTime.tryParse(raw['read_at']?.toString() ?? '');
            if (ts != null &&
                (_readHorizon == null || ts.isAfter(_readHorizon!))) {
              setState(() => _readHorizon = ts);
            }
          }
        case 'message_deleted':
          final id = raw['message_id']?.toString();
          if (id != null) {
            setState(() => _messages.removeWhere((m) => m.id == id));
          }
        case 'message_pinned' || 'message_unpinned':
          // Пин изменился у другого участника — перечитываем историю.
          // ignore: discarded_futures
          _loadHistory();
        case 'conversation_deleted':
          if (mounted) Navigator.of(context).maybePop();
        case 'conversation_cleared':
          setState(_messages.clear);
        default:
          break; // неизвестное событие — молча пропускаем
      }
      return;
    }

    final msg = ChatMessage.fromJson(raw);
    // Дедупликация: если WS-сообщение уже есть в списке (REST fallback) — пропустить
    if (_messages.any((m) => m.id == msg.id)) return;
    setState(() => _messages.add(msg));
    _scrollToBottom();
    // Отметить прочитанным при получении нового сообщения
    ChatRepository.instance.markRead(widget.conversation.id).catchError((_) {});
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollCtrl.hasClients) {
        _scrollCtrl.animateTo(
          _scrollCtrl.position.maxScrollExtent,
          duration: const Duration(milliseconds: 200),
          curve: Curves.easeOut,
        );
      }
    });
  }

  // Ответ на сообщение (веб _replyToId, правки 2026-06-24).
  ChatMessage? _replyTo;

  Future<void> _sendText() async {
    final text = _textCtrl.text.trim();
    if (text.isEmpty || _sending) return;
    _textCtrl.clear();
    final reply = _replyTo;
    setState(() => _replyTo = null);
    // Отправка через WS — сервер сам сбродкастит нам обратно и мы добавим через _onWsFrame.
    if (reply != null) {
      _ws.sendReply(text, reply.id);
    } else {
      _ws.send(text);
    }
  }

  // Долгое нажатие на сообщение: ответить / закрепить (веб msg-action-btn).
  void _showMessageActions(ChatMessage m) {
    // Удаление (правки 2026-07-21): автор — своё, менеджер/админ — любое
    // (зеркало прав бэка delete_message).
    final canDelete = m.senderId == _myUserId ||
        _myRole == 'admin' ||
        _myRole == 'manager';
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.reply),
              title: const Text('Ответить'),
              onTap: () {
                Navigator.pop(ctx);
                setState(() => _replyTo = m);
              },
            ),
            ListTile(
              leading: Icon(
                m.isPinned ? Icons.push_pin : Icons.push_pin_outlined,
              ),
              title: Text(m.isPinned ? 'Открепить' : 'Закрепить'),
              onTap: () async {
                Navigator.pop(ctx);
                try {
                  await ChatRepository.instance.pinMessage(
                    widget.conversation.id,
                    m.id,
                    pin: !m.isPinned,
                  );
                  await _loadHistory();
                } on Object catch (e) {
                  if (mounted) {
                    ScaffoldMessenger.of(
                      context,
                    ).showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
                  }
                }
              },
            ),
            if (canDelete)
              ListTile(
                leading: const Icon(Icons.delete_outline, color: Colors.red),
                title:
                    const Text('Удалить', style: TextStyle(color: Colors.red)),
                onTap: () {
                  Navigator.pop(ctx);
                  // ignore: discarded_futures
                  _deleteMessage(m);
                },
              ),
          ],
        ),
      ),
    );
  }

  /// Удалить сообщение с подтверждением; у остальных участников пузырь
  /// уберётся по WS-событию message_deleted.
  Future<void> _deleteMessage(ChatMessage m) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Удалить сообщение?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Отмена'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Удалить', style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ChatRepository.instance
          .deleteMessage(widget.conversation.id, m.id);
      if (mounted) {
        setState(() => _messages.removeWhere((x) => x.id == m.id));
      }
    } on Object catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
  }

  Future<void> _pickAndSendMedia(ImageSource source) async {
    setState(() => _sending = true);
    try {
      final XFile? picked;
      // Предлагаем выбор: фото или видео — через bottom sheet
      final mediaType = await _showMediaTypeSheet();
      if (mediaType == null) {
        setState(() => _sending = false);
        return;
      }
      if (mediaType == 'video') {
        picked = await _picker.pickVideo(source: source);
      } else {
        picked = await _picker.pickImage(source: source);
      }
      if (picked == null) {
        setState(() => _sending = false);
        return;
      }
      await ChatRepository.instance.sendAttachment(
        convId: widget.conversation.id,
        filePath: picked.path,
        fileName: picked.name,
      );
      // Сообщение придёт по WS broadcast — добавится через _onWsFrame.
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<String?> _showMediaTypeSheet() {
    return showModalBottomSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.image),
              title: const Text('Фото'),
              onTap: () => Navigator.pop(ctx, 'photo'),
            ),
            ListTile(
              leading: const Icon(Icons.videocam),
              title: const Text('Видео'),
              onTap: () => Navigator.pop(ctx, 'video'),
            ),
          ],
        ),
      ),
    );
  }

  void _showAttachmentOptions() {
    showModalBottomSheet(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.photo_library),
              title: const Text('Галерея'),
              onTap: () {
                Navigator.pop(ctx);
                _pickAndSendMedia(ImageSource.gallery);
              },
            ),
            ListTile(
              leading: const Icon(Icons.camera_alt),
              title: const Text('Камера'),
              onTap: () {
                Navigator.pop(ctx);
                _pickAndSendMedia(ImageSource.camera);
              },
            ),
            ListTile(
              leading: const Icon(Icons.attach_file),
              title: const Text('Файл'),
              subtitle: const Text('pdf, doc, xls, csv, txt, zip — до 25 МБ',
                  style: TextStyle(fontSize: 11)),
              onTap: () {
                Navigator.pop(ctx);
                _pickAndSendFile();
              },
            ),
          ],
        ),
      ),
    );
  }

  /// Вложение-файл (правки 2026-07-11): типы и лимит — как на бэке
  /// (_ATTACH_EXT_MIME, 25 МБ).
  static const _kFileMaxBytes = 25 * 1024 * 1024;
  static const _kFileExtensions = [
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv', 'txt', 'zip', 'rar', '7z',
  ];

  Future<void> _pickAndSendFile() async {
    setState(() => _sending = true);
    try {
      final result = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: _kFileExtensions,
      );
      final file = result?.files.singleOrNull;
      final path = file?.path;
      if (file == null || path == null) {
        setState(() => _sending = false);
        return;
      }
      if (file.size > _kFileMaxBytes) {
        setState(() => _sending = false);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('Файл больше 25 МБ')));
        }
        return;
      }
      await ChatRepository.instance.sendAttachment(
        convId: widget.conversation.id,
        filePath: path,
        fileName: file.name,
      );
      // Сообщение придёт по WS broadcast — добавится через _onWsFrame.
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  /// Позвонить участникам диалога (веб startCallFromChat): /calls/start
  /// возвращает токен LiveKit — сразу входим в комнату.
  /// _callBusy — защита от повторных тапов по 📞: каждый лишний тап
  /// создавал бы новый звонок (сервер дополнительно отсекает Conflict'ом).
  bool _callBusy = false;

  Future<void> _startCall() async {
    if (_callBusy) return;
    _callBusy = true;
    try {
      final token =
          await CallRepository.instance.start(widget.conversation.id);
      if (!mounted) return;
      await IncomingCallWatcher.instance.withInCall(() =>
          Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => CallScreen(
              token: token,
              remoteName: widget.conversation.displayTitle,
            ),
          )));
    } on Object catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    } finally {
      _callBusy = false;
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _readTimer?.cancel();
    _ws.dispose();
    _textCtrl.dispose();
    _scrollCtrl.dispose();
    super.dispose();
  }

  /// Статус исходящего сообщения для галочек. Для чужих — null (нет галочек).
  ///
  /// База — серверный m.status из GET /messages (sent/delivered/read,
  /// правки 2026-07-21); поверх — живой горизонт прочтения (read_receipt по WS
  /// или опрос): горизонт может быть свежее статуса, загруженного с историей.
  _MsgStatus? _statusFor(ChatMessage m) {
    final myId = _myUserId;
    if (myId == null || m.senderId != myId) return null;
    // Оптимистичное сообщение до подтверждения сервером имеет временный id.
    if (m.id.startsWith('tmp_')) return _MsgStatus.sending;
    final horizon = _readHorizon;
    if (m.status == 'read' ||
        (horizon != null && !m.createdAt.toUtc().isAfter(horizon.toUtc()))) {
      return _MsgStatus.read;
    }
    if (m.status == 'delivered') return _MsgStatus.delivered;
    return _MsgStatus.sent;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.conversation.displayTitle),
        actions: [
          IconButton(
            tooltip: 'Позвонить',
            icon: const Icon(Icons.call_outlined),
            onPressed: _startCall,
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : ListView.builder(
                    controller: _scrollCtrl,
                    padding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 8,
                    ),
                    itemCount: _messages.length,
                    itemBuilder: (context, i) => GestureDetector(
                      onLongPress: () => _showMessageActions(_messages[i]),
                      child: _MessageBubble(
                        msg: _messages[i],
                        status: _statusFor(_messages[i]),
                      ),
                    ),
                  ),
          ),
          if (_replyTo != null)
            Container(
              padding: const EdgeInsets.fromLTRB(12, 6, 4, 6),
              color: Theme.of(context).colorScheme.surfaceContainerHigh,
              child: Row(
                children: [
                  const Icon(Icons.reply, size: 16),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Ответ: ${_replyTo!.senderName} — ${_replyTo!.text}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 12),
                    ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.close, size: 16),
                    onPressed: () => setState(() => _replyTo = null),
                  ),
                ],
              ),
            ),
          _ComposeBar(
            controller: _textCtrl,
            onSend: _sendText,
            onAttach: _showAttachmentOptions,
            sending: _sending,
          ),
        ],
      ),
    );
  }
}

// ── Статус доставки сообщения (галочки) ──────────────────────────────────────

/// sending — часики (оптимистичное, ещё не подтверждено), sent — одна галочка
/// (сервер принял), read — две (собеседник открыл чат после этого сообщения).
enum _MsgStatus { sending, sent, delivered, read }

class _StatusTicks extends StatelessWidget {
  const _StatusTicks({required this.status, required this.color});

  final _MsgStatus status;
  final Color color;

  /// Две «слипшиеся» галочки: серые — доставлено, акцентные — прочитано.
  Widget _doubleTicks(Color c) => SizedBox(
        width: 18,
        height: 14,
        child: Stack(
          children: [
            Icon(Icons.check, size: 14, color: c),
            Positioned(
              left: 4,
              child: Icon(Icons.check, size: 14, color: c),
            ),
          ],
        ),
      );

  @override
  Widget build(BuildContext context) {
    switch (status) {
      case _MsgStatus.sending:
        return Icon(Icons.schedule,
            size: 12, color: Colors.grey.shade500);
      case _MsgStatus.sent:
        return Icon(Icons.check, size: 14, color: Colors.grey.shade500);
      case _MsgStatus.delivered:
        return _doubleTicks(Colors.grey.shade500);
      case _MsgStatus.read:
        return _doubleTicks(color);
    }
  }
}

// ── Пузырь сообщения ──────────────────────────────────────────────────────────

class _MessageBubble extends StatelessWidget {
  const _MessageBubble({required this.msg, this.status});
  final ChatMessage msg;

  /// Статус доставки для исходящих (null — входящее, без галочек).
  final _MsgStatus? status;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                '${msg.senderName} · ${_fmtTime(msg.createdAt)}',
                style: theme.textTheme.labelSmall?.copyWith(
                  color: theme.colorScheme.outline,
                ),
              ),
              if (status != null) ...[
                const SizedBox(width: 4),
                _StatusTicks(status: status!, color: theme.colorScheme.primary),
              ],
            ],
          ),
          const SizedBox(height: 2),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: theme.colorScheme.surfaceContainerLow,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Цитата-ответ (reply_preview, правки 2026-06-24)
                if (msg.replyPreview != null)
                  Container(
                    margin: const EdgeInsets.only(bottom: 6),
                    padding: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 4,
                    ),
                    decoration: BoxDecoration(
                      border: Border(
                        left: BorderSide(
                          width: 3,
                          color: theme.colorScheme.primary,
                        ),
                      ),
                      color: theme.colorScheme.surfaceContainerHigh,
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          msg.replyPreview!.senderName,
                          style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w600,
                            color: theme.colorScheme.primary,
                          ),
                        ),
                        Text(
                          msg.replyPreview!.text,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(fontSize: 12),
                        ),
                      ],
                    ),
                  ),
                _buildContent(context),
              ],
            ),
          ),
          if (msg.isPinned)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    Icons.push_pin,
                    size: 12,
                    color: theme.colorScheme.outline,
                  ),
                  const SizedBox(width: 4),
                  Text(
                    'закреплено',
                    style: theme.textTheme.labelSmall?.copyWith(
                      color: theme.colorScheme.outline,
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildContent(BuildContext context) {
    if (msg.isPhoto) return _PhotoContent(msg: msg);
    if (msg.isVideo) return _VideoContent(msg: msg);
    if (msg.isDocument) return _DocumentContent(msg: msg);
    if (msg.isFile) return _FileContent(msg: msg);
    return Text(msg.text);
  }

  String _fmtTime(DateTime dt) {
    final local = dt.toLocal();
    final h = local.hour.toString().padLeft(2, '0');
    final m = local.minute.toString().padLeft(2, '0');
    return '$h:$m';
  }
}

// ── Рендер вложений ───────────────────────────────────────────────────────────

class _PhotoContent extends StatelessWidget {
  const _PhotoContent({required this.msg});
  final ChatMessage msg;

  @override
  Widget build(BuildContext context) {
    final url = msg.attachmentUrl(AppConfig.chatBase);
    if (url.isEmpty) return Text(msg.text);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _AuthImage(url: url),
        if (msg.text.isNotEmpty && msg.metadata?['original_name'] != msg.text)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(msg.text, style: const TextStyle(fontSize: 12)),
          ),
      ],
    );
  }
}

/// Файл-вложение pdf/doc/xls/zip (правки 2026-07-11): пузырь с иконкой
/// и именем, тап скачивает во временную папку и открывает системным
/// приложением (open_filex).
class _FileContent extends StatefulWidget {
  const _FileContent({required this.msg});
  final ChatMessage msg;

  @override
  State<_FileContent> createState() => _FileContentState();
}

class _FileContentState extends State<_FileContent> {
  bool _downloading = false;

  Future<void> _openFile() async {
    if (_downloading) return;
    final msg = widget.msg;
    final url = msg.attachmentUrl(AppConfig.chatBase);
    if (url.isEmpty) return;
    setState(() => _downloading = true);
    try {
      final name = (msg.metadata?['original_name'] as String?) ??
          (msg.text.isNotEmpty ? msg.text : 'file');
      final dir = await getTemporaryDirectory();
      // Имя из сообщения могло содержать разделители — оставляем безопасное.
      final safeName = name.replaceAll(RegExp(r'[\\/:*?"<>|]'), '_');
      final path = '${dir.path}/$safeName';
      await ApiClient.instance.dio.download(url, path);
      final result = await OpenFilex.open(path);
      if (result.type != ResultType.done && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('Не удалось открыть файл: ${result.message}')));
      }
    } on Object catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    } finally {
      if (mounted) setState(() => _downloading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final msg = widget.msg;
    final name =
        msg.metadata?['original_name'] as String? ?? msg.text;
    return InkWell(
      onTap: _openFile,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          _downloading
              ? const SizedBox(
                  width: 28,
                  height: 28,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.insert_drive_file_outlined, size: 28),
          const SizedBox(width: 8),
          Flexible(
            child: Text(
              name,
              style: TextStyle(
                color: Theme.of(context).colorScheme.primary,
                decoration: TextDecoration.underline,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _VideoContent extends StatelessWidget {
  const _VideoContent({required this.msg});
  final ChatMessage msg;

  @override
  Widget build(BuildContext context) {
    final url = msg.attachmentUrl(AppConfig.chatBase);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(Icons.videocam_outlined, size: 32),
        const SizedBox(width: 8),
        Flexible(
          child: InkWell(
            onTap: () {
              // Открыть во внешнем плеере — для v1 достаточно
              ScaffoldMessenger.of(
                context,
              ).showSnackBar(SnackBar(content: Text('Видео: $url')));
            },
            child: Text(
              msg.metadata?['original_name'] as String? ?? msg.text,
              style: TextStyle(
                color: Theme.of(context).colorScheme.primary,
                decoration: TextDecoration.underline,
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _DocumentContent extends StatelessWidget {
  const _DocumentContent({required this.msg});
  final ChatMessage msg;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(Icons.insert_drive_file_outlined, size: 32),
        const SizedBox(width: 8),
        Flexible(
          child: Text(msg.metadata?['original_name'] as String? ?? msg.text),
        ),
      ],
    );
  }
}

/// Изображение, загружаемое с добавлением Bearer-токена в заголовок.
class _AuthImage extends StatefulWidget {
  const _AuthImage({required this.url});
  final String url;

  @override
  State<_AuthImage> createState() => _AuthImageState();
}

class _AuthImageState extends State<_AuthImage> {
  File? _file;
  bool _loading = true;
  bool _error = false;

  @override
  void initState() {
    super.initState();
    _download();
  }

  Future<void> _download() async {
    try {
      final token = await TokenStorage.instance.accessToken;
      final resp = await ApiClient.instance.dio.get<List<int>>(
        widget.url,
        options: Options(
          responseType: ResponseType.bytes,
          headers: {if (token != null) 'Authorization': 'Bearer $token'},
        ),
      );
      final tmpDir = Directory.systemTemp;
      final name = widget.url.split('/').last;
      final file = File('${tmpDir.path}/$name');
      await file.writeAsBytes(resp.data!);
      if (mounted)
        setState(() {
          _file = file;
          _loading = false;
        });
    } catch (_) {
      if (mounted)
        setState(() {
          _loading = false;
          _error = true;
        });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const SizedBox(
        width: 200,
        height: 120,
        child: Center(child: CircularProgressIndicator()),
      );
    }
    if (_error || _file == null) {
      return const Icon(Icons.broken_image_outlined, size: 48);
    }
    return ClipRRect(
      borderRadius: BorderRadius.circular(8),
      child: Image.file(_file!, width: 200, fit: BoxFit.cover),
    );
  }
}

// ── Строка ввода ──────────────────────────────────────────────────────────────

class _ComposeBar extends StatelessWidget {
  const _ComposeBar({
    required this.controller,
    required this.onSend,
    required this.onAttach,
    required this.sending,
  });

  final TextEditingController controller;
  final VoidCallback onSend;
  final VoidCallback onAttach;
  final bool sending;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(8, 4, 8, 8),
        child: Row(
          children: [
            IconButton(
              icon: const Icon(Icons.attach_file),
              onPressed: sending ? null : onAttach,
              tooltip: 'Вложение',
            ),
            Expanded(
              child: TextField(
                controller: controller,
                maxLines: null,
                maxLength: 4000,
                keyboardType: TextInputType.multiline,
                textInputAction: TextInputAction.newline,
                decoration: const InputDecoration(
                  hintText: 'Сообщение…',
                  border: OutlineInputBorder(),
                  contentPadding: EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 8,
                  ),
                  counterText: '',
                ),
              ),
            ),
            const SizedBox(width: 4),
            sending
                ? const Padding(
                    padding: EdgeInsets.all(12),
                    child: SizedBox(
                      width: 24,
                      height: 24,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                  )
                : IconButton(
                    icon: const Icon(Icons.send),
                    onPressed: onSend,
                    tooltip: 'Отправить',
                  ),
          ],
        ),
      ),
    );
  }
}
