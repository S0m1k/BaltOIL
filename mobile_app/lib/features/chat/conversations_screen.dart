import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../auth/auth_repository.dart';
import 'chat_models.dart';
import 'chat_repository.dart';
import 'chat_screen.dart';

/// Список диалогов текущего пользователя.
class ConversationsScreen extends StatefulWidget {
  const ConversationsScreen({super.key});

  @override
  State<ConversationsScreen> createState() => _ConversationsScreenState();
}

class _ConversationsScreenState extends State<ConversationsScreen> {
  late Future<List<Conversation>> _future;
  CurrentUser? _user;

  @override
  void initState() {
    super.initState();
    _load();
    _loadUser();
  }

  void _load() {
    setState(() {
      _future = ChatRepository.instance.listConversations();
    });
  }

  Future<void> _loadUser() async {
    try {
      final u = await AuthRepository.instance.me();
      if (mounted) setState(() => _user = u);
    } catch (_) {}
  }

  void _openChat(Conversation conv) {
    Navigator.of(context)
        .push(MaterialPageRoute(
          builder: (_) => ChatScreen(conversation: conv),
        ))
        .then((_) => _load()); // обновить список после возврата (прочитано)
  }

  /// Диалог ввода номера телефона для start-by-phone.
  Future<void> _startByPhone() async {
    final ctrl = TextEditingController();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Новый чат по номеру'),
        content: TextField(
          controller: ctrl,
          keyboardType: TextInputType.phone,
          decoration: const InputDecoration(labelText: 'Номер телефона'),
          autofocus: true,
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Отмена')),
          TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Начать')),
        ],
      ),
    );
    if (confirmed != true || ctrl.text.trim().isEmpty) return;
    try {
      final conv =
          await ChatRepository.instance.startByPhone(ctrl.text.trim());
      if (mounted) _openChat(conv);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(apiErrorMessage(e))),
        );
      }
    }
  }

  /// Чат клиент–бухгалтер (только client-company или manager/admin).
  Future<void> _openAccountantChat() async {
    try {
      final conv = await ChatRepository.instance.ensureClientAccountant();
      if (mounted) _openChat(conv);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(apiErrorMessage(e))),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final role = _user?.role ?? '';
    final isStaff = role == 'manager' || role == 'admin';
    final isClient = role == 'client';

    return Scaffold(
      appBar: AppBar(title: const Text('Чаты')),
      // FAB с меню: у staff — start-by-phone; у клиентов-юрлиц — бухгалтер.
      // У всех — start-by-phone (сервер сам проверит роль/блокировку).
      floatingActionButton: FloatingActionButton(
        onPressed: _startByPhone,
        tooltip: 'Новый чат',
        child: const Icon(Icons.chat_bubble_outline),
      ),
      body: Column(
        children: [
          // Быстрые кнопки-экшены для нужных ролей
          if (isClient)
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
              child: OutlinedButton.icon(
                icon: const Icon(Icons.account_balance),
                label: const Text('Чат с бухгалтером'),
                onPressed: _openAccountantChat,
              ),
            ),
          if (isStaff)
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
              child: OutlinedButton.icon(
                icon: const Icon(Icons.phone),
                label: const Text('Найти клиента по телефону'),
                onPressed: _startByPhone,
              ),
            ),
          const SizedBox(height: 8),
          Expanded(
            child: RefreshIndicator(
              onRefresh: () async => _load(),
              child: FutureBuilder<List<Conversation>>(
                future: _future,
                builder: (context, snap) {
                  if (snap.connectionState != ConnectionState.done) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  if (snap.hasError) {
                    return _ErrorRetry(
                        message: apiErrorMessage(snap.error!),
                        onRetry: _load);
                  }
                  final convs = snap.data ?? const [];
                  if (convs.isEmpty) {
                    return ListView(children: const [
                      SizedBox(height: 120),
                      Center(child: Text('Диалогов пока нет')),
                    ]);
                  }
                  // Закреплённые — первыми
                  final sorted = [...convs]..sort((a, b) {
                      if (a.isPinned == b.isPinned) {
                        return b.updatedAt.compareTo(a.updatedAt);
                      }
                      return a.isPinned ? -1 : 1;
                    });
                  return ListView.separated(
                    itemCount: sorted.length,
                    separatorBuilder: (_, _) => const Divider(height: 1),
                    itemBuilder: (context, i) => _ConvTile(
                      conv: sorted[i],
                      onTap: () => _openChat(sorted[i]),
                    ),
                  );
                },
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ConvTile extends StatelessWidget {
  const _ConvTile({required this.conv, required this.onTap});
  final Conversation conv;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final subtitle = conv.lastMessage?.text ?? '';
    return ListTile(
      leading: CircleAvatar(
        backgroundColor: theme.colorScheme.primaryContainer,
        child: Text(
          conv.displayTitle.isNotEmpty ? conv.displayTitle[0].toUpperCase() : '?',
          style: TextStyle(color: theme.colorScheme.onPrimaryContainer),
        ),
      ),
      title: Row(
        children: [
          if (conv.isPinned)
            Padding(
              padding: const EdgeInsets.only(right: 4),
              child: Icon(Icons.push_pin, size: 14,
                  color: theme.colorScheme.primary),
            ),
          Expanded(
            child: Text(conv.displayTitle,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontWeight: FontWeight.w600)),
          ),
        ],
      ),
      subtitle: subtitle.isNotEmpty
          ? Text(subtitle,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: theme.textTheme.bodySmall)
          : null,
      trailing: conv.unreadCount > 0
          ? Badge(
              label: Text('${conv.unreadCount}'),
              child: const Icon(Icons.chat_bubble_outline, size: 20),
            )
          : null,
      onTap: onTap,
    );
  }
}

class _ErrorRetry extends StatelessWidget {
  const _ErrorRetry({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(message, textAlign: TextAlign.center),
          const SizedBox(height: 12),
          ElevatedButton(onPressed: onRetry, child: const Text('Повторить')),
        ]),
      ),
    );
  }
}
