import 'package:flutter/material.dart';

import '../auth/auth_repository.dart';
import '../auth/login_screen.dart';
import '../chat/conversations_screen.dart';
import '../notifications/notifications_repository.dart';
import '../notifications/notifications_screen.dart';
import '../orders/driver_orders_screen.dart';
import '../orders/orders_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _tab = 0;
  CurrentUser? _user;
  int _unread = 0;

  @override
  void initState() {
    super.initState();
    _loadUser();
    _refreshUnread();
  }

  Future<void> _refreshUnread() async {
    try {
      final count = await NotificationsRepository.instance.unreadCount();
      if (mounted) setState(() => _unread = count);
    } catch (_) {
      // Badge — некритичная информация, ошибку глотаем.
    }
  }

  Future<void> _loadUser() async {
    try {
      final user = await AuthRepository.instance.me();
      if (mounted) setState(() => _user = user);
    } catch (_) {
      // 401 обработает интерцептор (refresh → или выход на логин).
    }
  }

  Future<void> _logout() async {
    await AuthRepository.instance.logout();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (_) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    final user = _user;
    final isDriver = user?.role == 'driver';
    final isClient = user == null || user.role == 'client';

    // Профиль ещё грузится — без него не знаем, какой экран заявок показывать.
    final Widget ordersBody;
    if (user == null) {
      ordersBody = const Center(child: CircularProgressIndicator());
    } else if (isDriver) {
      ordersBody = DriverOrdersScreen(driverId: user.id);
    } else {
      ordersBody = OrdersScreen(canCreate: isClient);
    }

    String appBarTitle;
    if (_tab == 0) {
      appBarTitle = isDriver ? 'Заявки на доставку' : 'Мои заявки';
    } else if (_tab == 1) {
      appBarTitle = 'Чаты';
    } else {
      appBarTitle = 'Уведомления';
    }

    return Scaffold(
      appBar: AppBar(
        title: Text(appBarTitle),
        actions: [
          if (_user != null)
            Padding(
              padding: const EdgeInsets.only(right: 4),
              child: Center(
                  child: Text(_user!.fullName,
                      style: Theme.of(context).textTheme.bodySmall)),
            ),
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: 'Выйти',
            onPressed: _logout,
          ),
        ],
      ),
      body: IndexedStack(
        index: _tab,
        children: [
          ordersBody,
          const ConversationsScreen(),
          const NotificationsScreen(),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) {
          setState(() => _tab = i);
          _refreshUnread();
        },
        destinations: [
          const NavigationDestination(
              icon: Icon(Icons.local_shipping_outlined),
              selectedIcon: Icon(Icons.local_shipping),
              label: 'Заявки'),
          const NavigationDestination(
              icon: Icon(Icons.chat_bubble_outline),
              selectedIcon: Icon(Icons.chat_bubble),
              label: 'Чаты'),
          NavigationDestination(
              icon: Badge(
                isLabelVisible: _unread > 0,
                label: Text('$_unread'),
                child: const Icon(Icons.notifications_outlined),
              ),
              selectedIcon: const Icon(Icons.notifications),
              label: 'Уведомления'),
        ],
      ),
    );
  }
}
