import 'package:flutter/material.dart';

import '../auth/auth_repository.dart';
import '../auth/login_screen.dart';
import '../notifications/notifications_screen.dart';
import '../orders/orders_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _tab = 0;
  CurrentUser? _user;

  @override
  void initState() {
    super.initState();
    _loadUser();
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
    final isClient = _user == null || _user!.role == 'client';
    return Scaffold(
      appBar: AppBar(
        title: Text(_tab == 0 ? 'Мои заявки' : 'Уведомления'),
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
          OrdersScreen(canCreate: isClient),
          const NotificationsScreen(),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: const [
          NavigationDestination(
              icon: Icon(Icons.local_shipping_outlined),
              selectedIcon: Icon(Icons.local_shipping),
              label: 'Заявки'),
          NavigationDestination(
              icon: Icon(Icons.notifications_outlined),
              selectedIcon: Icon(Icons.notifications),
              label: 'Уведомления'),
        ],
      ),
    );
  }
}
