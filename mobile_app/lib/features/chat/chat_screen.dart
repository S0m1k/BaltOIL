import 'dart:io';

import 'package:dio/dio.dart' show Options, ResponseType;
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/api_client.dart';
import '../../core/app_config.dart';
import '../../core/token_storage.dart';
import '../../core/ws_client.dart';
import 'chat_models.dart';
import 'chat_repository.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key, required this.conversation});

  final Conversation conversation;

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen>
    with WidgetsBindingObserver {
  final _textCtrl = TextEditingController();
  final _scrollCtrl = ScrollController();
  final _picker = ImagePicker();

  late ChatWsClient _ws;
  final List<ChatMessage> _messages = [];
  bool _loading = true;
  bool _sending = false;

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
  }

  Future<void> _loadHistory() async {
    try {
      final msgs = await ChatRepository.instance
          .fetchHistory(widget.conversation.id, limit: 50);
      // История приходит от старых к новым — порядок уже верный для ListView
      if (mounted) {
        setState(() {
          _messages.clear();
          _messages.addAll(msgs);
          _loading = false;
        });
      }
      // Отметить прочитанными в фоне — некритично
      ChatRepository.instance.markRead(widget.conversation.id).catchError((_) {});
    } catch (e) {
      if (mounted) {
        setState(() => _loading = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(apiErrorMessage(e))),
        );
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
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(err)));
      }
      return;
    }
    final msg = ChatMessage.fromJson(frame.message!);
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

  Future<void> _sendText() async {
    final text = _textCtrl.text.trim();
    if (text.isEmpty || _sending) return;
    _textCtrl.clear();
    // Отправка через WS — сервер сам сбродкастит нам обратно и мы добавим через _onWsFrame.
    _ws.send(text);
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
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(apiErrorMessage(e))),
        );
      }
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<String?> _showMediaTypeSheet() {
    return showModalBottomSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
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
        ]),
      ),
    );
  }

  void _showAttachmentOptions() {
    showModalBottomSheet(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
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
        ]),
      ),
    );
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _ws.dispose();
    _textCtrl.dispose();
    _scrollCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.conversation.displayTitle)),
      body: Column(
        children: [
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : ListView.builder(
                    controller: _scrollCtrl,
                    padding: const EdgeInsets.symmetric(
                        horizontal: 12, vertical: 8),
                    itemCount: _messages.length,
                    itemBuilder: (context, i) =>
                        _MessageBubble(msg: _messages[i]),
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

// ── Пузырь сообщения ──────────────────────────────────────────────────────────

class _MessageBubble extends StatelessWidget {
  const _MessageBubble({required this.msg});
  final ChatMessage msg;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '${msg.senderName} · ${_fmtTime(msg.createdAt)}',
            style: theme.textTheme.labelSmall
                ?.copyWith(color: theme.colorScheme.outline),
          ),
          const SizedBox(height: 2),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: theme.colorScheme.surfaceContainerLow,
              borderRadius: BorderRadius.circular(12),
            ),
            child: _buildContent(context),
          ),
        ],
      ),
    );
  }

  Widget _buildContent(BuildContext context) {
    if (msg.isPhoto) return _PhotoContent(msg: msg);
    if (msg.isVideo) return _VideoContent(msg: msg);
    if (msg.isDocument) return _DocumentContent(msg: msg);
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
        if (msg.text.isNotEmpty &&
            msg.metadata?['original_name'] != msg.text)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(msg.text, style: const TextStyle(fontSize: 12)),
          ),
      ],
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
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(content: Text('Видео: $url')),
              );
            },
            child: Text(
              msg.metadata?['original_name'] as String? ?? msg.text,
              style: TextStyle(
                  color: Theme.of(context).colorScheme.primary,
                  decoration: TextDecoration.underline),
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
          child: Text(
            msg.metadata?['original_name'] as String? ?? msg.text,
          ),
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
      if (mounted) setState(() { _file = file; _loading = false; });
    } catch (_) {
      if (mounted) setState(() { _loading = false; _error = true; });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const SizedBox(
        width: 200, height: 120,
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
                  contentPadding:
                      EdgeInsets.symmetric(horizontal: 12, vertical: 8),
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
                        child: CircularProgressIndicator(strokeWidth: 2)),
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
