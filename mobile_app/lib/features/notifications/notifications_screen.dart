import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../auth/auth_repository.dart';
import '../chat/chat_repository.dart';
import '../chat/chat_screen.dart';
import '../orders/order_detail_screen.dart';
import 'notifications_repository.dart';

class NotificationsScreen extends StatefulWidget {
  const NotificationsScreen({super.key, required this.user});

  /// Нужен экрану заявки (права и набор действий зависят от роли).
  final CurrentUser user;

  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  late Future<List<AppNotification>> _future;

  @override
  void initState() {
    super.initState();
    _future = NotificationsRepository.instance.list();
  }

  Future<void> _reload() async {
    final future = NotificationsRepository.instance.list();
    setState(() {
      _future = future;
    });
    await future;
  }

  Future<void> _markAllRead() async {
    await NotificationsRepository.instance.markAllRead();
    _reload();
  }

  /// Тап по уведомлению: пометить прочитанным; уведомление о сообщении
  /// открывает этот чат (веб readNotif, 2026-07-15), о заявке — карточку
  /// заявки (правки 2026-09-14: раньше тап по «новой заявке» и «изменениям»
  /// ничего не делал). Навигация — даже если пометка «прочитано» не удалась.
  Future<void> _onTap(AppNotification n) async {
    final orderId = n.entityId;
    if (n.opensOrder && orderId != null) {
      // Помечаем до перехода: вернувшись назад, человек видит список уже
      // без «жирного» уведомления, а не прежнее состояние.
      await _markRead(n);
      if (!mounted) return;
      await Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => OrderDetailScreen(orderId: orderId, user: widget.user),
      ));
      return;
    }
    if (n.opensChat) {
      try {
        final convs = await ChatRepository.instance.listConversations();
        final conv = convs.where((c) => c.id == n.entityId).firstOrNull;
        if (conv != null && mounted) {
          await Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => ChatScreen(conversation: conv),
          ));
        }
      } on Object {
        // Чат недоступен — остаёмся в списке уведомлений.
      }
    }
    await _markRead(n);
  }

  Future<void> _markRead(AppNotification n) async {
    if (n.isRead) return;
    try {
      await NotificationsRepository.instance.markRead(n.id);
    } on Object {
      // Пометка не удалась — список просто не обновится.
    }
    if (mounted) _reload();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: RefreshIndicator(
        onRefresh: _reload,
        child: FutureBuilder<List<AppNotification>>(
          future: _future,
          builder: (context, snap) {
            if (snap.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snap.hasError) {
              return ListView(children: [
                const SizedBox(height: 120),
                Center(child: Text(apiErrorMessage(snap.error!))),
                Center(
                    child: OutlinedButton(
                        onPressed: _reload, child: const Text('Повторить'))),
              ]);
            }
            final items = snap.data ?? const [];
            if (items.isEmpty) {
              return ListView(children: const [
                SizedBox(height: 120),
                Center(child: Text('Уведомлений нет')),
              ]);
            }
            return ListView.separated(
              itemCount: items.length + 1,
              separatorBuilder: (_, _) => const Divider(height: 1),
              itemBuilder: (context, i) {
                if (i == 0) {
                  return Align(
                    alignment: Alignment.centerRight,
                    child: TextButton(
                      onPressed: _markAllRead,
                      child: const Text('Прочитать все'),
                    ),
                  );
                }
                final n = items[i - 1];
                return ListTile(
                  leading: Icon(
                    n.isRead
                        ? Icons.notifications_none
                        : Icons.notifications_active,
                    color: n.isRead ? Colors.grey : Colors.blue,
                  ),
                  title: Text(n.title,
                      style: TextStyle(
                          fontWeight:
                              n.isRead ? FontWeight.normal : FontWeight.w600)),
                  subtitle: Text(n.body),
                  trailing: n.isNavigable
                      ? const Icon(Icons.chevron_right, size: 20)
                      : null,
                  onTap: n.isRead && !n.isNavigable ? null : () => _onTap(n),
                );
              },
            );
          },
        ),
      ),
    );
  }
}
