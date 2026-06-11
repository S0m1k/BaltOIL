import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import 'notifications_repository.dart';

class NotificationsScreen extends StatefulWidget {
  const NotificationsScreen({super.key});

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
                  onTap: n.isRead
                      ? null
                      : () async {
                          await NotificationsRepository.instance.markRead(n.id);
                          _reload();
                        },
                );
              },
            );
          },
        ),
      ),
    );
  }
}
