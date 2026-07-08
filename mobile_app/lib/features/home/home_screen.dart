import 'package:flutter/material.dart';

import '../../core/theme.dart';
import '../../core/theme_controller.dart';
import '../auth/auth_repository.dart';
import '../auth/login_screen.dart';
import '../chat/conversations_screen.dart';
import '../clients/clients_screen.dart';
import '../finance/finance_screen.dart';
import '../inventory/inventory_screen.dart';
import '../notifications/notifications_repository.dart';
import '../notifications/notifications_screen.dart';
import '../orders/driver_orders_screen.dart';
import '../orders/order_create_screen.dart';
import '../orders/orders_screen.dart';
import '../fuels/fuels_screen.dart';
import '../organizations/organizations_screen.dart';
import '../vehicles/vehicles_screen.dart';
import '../profile/profile_screen.dart';
import '../report/report_screen.dart';
import '../requisites/requisites_screen.dart';
import '../tariffs/tariffs_screen.dart';
import '../trips/trips_screen.dart';
import '../users/users_screen.dart';
import '../zones/zones_screen.dart';

// ---------------------------------------------------------------------------
// Destination enum — mirrors web sidebar order.
// ---------------------------------------------------------------------------
enum _Dest {
  orders,
  createOrder,
  orgs,
  vehicles,
  trips,
  finance,
  inventory,
  fuels,
  tariffs,
  report,
  clients,
  users,
  requisites,
  zones,
  chat,
  notifications,
  profile,
}

// ---------------------------------------------------------------------------
// Role helpers
// ---------------------------------------------------------------------------
const _roleLabels = {
  'admin': 'Админ',
  'manager': 'Менеджер',
  'driver': 'Водитель',
  'client': 'Клиент',
};

bool _allowed(String role, _Dest dest) => switch (dest) {
      _Dest.orders => true,
      _Dest.createOrder =>
        role == 'client' || role == 'manager' || role == 'admin',
      // Организации — все кроме водителя (веб: show role !== 'driver')
      _Dest.orgs => role != 'driver',
      // ТС — все кроме клиента (веб: show role !== 'client')
      _Dest.vehicles => role != 'client',
      _Dest.trips =>
        role == 'admin' || role == 'manager' || role == 'driver',
      _Dest.finance => role == 'admin' || role == 'manager',
      _Dest.inventory =>
        role == 'admin' || role == 'manager' || role == 'driver',
      // Топливо — справочник, виден всем (веб: show true)
      _Dest.fuels => true,
      _Dest.tariffs => role == 'admin' || role == 'manager',
      _Dest.report =>
        role == 'admin' || role == 'manager' || role == 'driver',
      _Dest.clients => role == 'admin' || role == 'manager',
      _Dest.users => role == 'admin' || role == 'manager',
      _Dest.requisites => role == 'admin',
      _Dest.zones => role == 'admin',
      _Dest.chat => true,
      _Dest.notifications => true,
      _Dest.profile => true,
    };

String _destLabel(_Dest dest, [String? role]) => switch (dest) {
      _Dest.orders => 'Заявки',
      _Dest.createOrder => 'Создать заявку',
      // Как на вебе: клиенту — «Мои организации», staff — «Организации»
      _Dest.orgs =>
        role == 'client' ? 'Мои организации' : 'Организации',
      _Dest.vehicles => 'ТС',
      _Dest.trips => 'Рейсы',
      _Dest.finance => 'Финансы',
      _Dest.inventory => 'Склад',
      _Dest.fuels => 'Топливо',
      _Dest.tariffs => 'Тарифы',
      _Dest.report => 'Отчёт',
      _Dest.clients => 'Клиенты',
      _Dest.users => 'Пользователи',
      _Dest.requisites => 'Реквизиты',
      _Dest.zones => 'Зоны',
      _Dest.chat => 'Чат',
      _Dest.notifications => 'Уведомления',
      _Dest.profile => 'Профиль',
    };

IconData _destIcon(_Dest dest) => switch (dest) {
      _Dest.orders => Icons.local_shipping,
      _Dest.createOrder => Icons.add_box,
      _Dest.orgs => Icons.business_center,
      _Dest.vehicles => Icons.local_shipping_outlined,
      _Dest.trips => Icons.route,
      _Dest.finance => Icons.payments,
      _Dest.inventory => Icons.inventory_2,
      _Dest.fuels => Icons.local_gas_station,
      _Dest.tariffs => Icons.request_quote,
      _Dest.report => Icons.assessment,
      _Dest.clients => Icons.groups,
      _Dest.users => Icons.manage_accounts,
      _Dest.requisites => Icons.business,
      _Dest.zones => Icons.map,
      _Dest.chat => Icons.chat_bubble,
      _Dest.notifications => Icons.notifications,
      _Dest.profile => Icons.person,
    };

// ---------------------------------------------------------------------------
// HomeScreen
// ---------------------------------------------------------------------------
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  _Dest _dest = _Dest.orders;
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
    } on Exception {
      // Badge — некритичная информация.
    }
  }

  Future<void> _loadUser() async {
    try {
      final user = await AuthRepository.instance.me();
      if (mounted) setState(() => _user = user);
    } on Exception {
      // 401 обработает интерцептор.
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

  void _select(_Dest dest) {
    Navigator.of(context).pop(); // close drawer
    if (dest == _Dest.createOrder) {
      final user = _user;
      if (user == null) return; // профиль ещё грузится
      // Push as full route; return to orders after.
      Navigator.of(context)
          .push(MaterialPageRoute(
              builder: (_) => OrderCreateScreen(user: user)))
          .then((_) => setState(() => _dest = _Dest.orders));
      return;
    }
    setState(() {
      _dest = dest;
      if (dest == _Dest.notifications) _refreshUnread();
    });
  }

  // -------------------------------------------------------------------------
  // Body builder
  // -------------------------------------------------------------------------
  Widget _buildBody() {
    final user = _user;
    if (user == null) {
      return const Center(child: CircularProgressIndicator());
    }
    return switch (_dest) {
      _Dest.orders => user.role == 'driver'
          ? DriverOrdersScreen(driverId: user.id)
          : OrdersScreen(
              canCreate: user.role == 'client' ||
                  user.role == 'manager' ||
                  user.role == 'admin',
              user: user,
            ),
      _Dest.createOrder => const Center(child: CircularProgressIndicator()),
      _Dest.orgs => OrganizationsScreen(user: user),
      _Dest.vehicles => VehiclesScreen(user: user),
      _Dest.trips => TripsScreen(user: user),
      _Dest.finance => FinanceScreen(user: user),
      _Dest.inventory => InventoryScreen(user: user),
      _Dest.fuels => const FuelsScreen(),
      _Dest.tariffs => TariffsScreen(user: user),
      _Dest.report => ReportScreen(user: user),
      _Dest.clients => ClientsScreen(user: user),
      _Dest.users => UsersScreen(user: user),
      _Dest.requisites => RequisitesScreen(user: user),
      _Dest.zones => ZonesScreen(user: user),
      _Dest.chat => const ConversationsScreen(),
      _Dest.notifications => const NotificationsScreen(),
      _Dest.profile => ProfileScreen(user: user),
    };
  }

  // -------------------------------------------------------------------------
  // AppBar title
  // -------------------------------------------------------------------------
  String get _appBarTitle {
    if (_dest == _Dest.orders) {
      return _user?.role == 'driver' ? 'Заявки на доставку' : 'Мои заявки';
    }
    return _destLabel(_dest, _user?.role);
  }

  // -------------------------------------------------------------------------
  // Build
  // -------------------------------------------------------------------------
  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    final user = _user;

    return Scaffold(
      appBar: AppBar(
        title: Text(_appBarTitle),
        actions: [
          // Theme toggle
          IconButton(
            icon: Icon(brightness == Brightness.dark
                ? Icons.light_mode
                : Icons.dark_mode),
            tooltip: 'Тёмная/светлая тема',
            onPressed: () => ThemeController.instance.toggle(brightness),
          ),
          // Notification bell with badge
          IconButton(
            icon: Badge(
              isLabelVisible: _unread > 0,
              label: Text('$_unread'),
              child: const Icon(Icons.notifications_outlined),
            ),
            tooltip: 'Уведомления',
            onPressed: () => setState(() {
              _dest = _Dest.notifications;
              _refreshUnread();
            }),
          ),
          // User chip
          if (user != null)
            GestureDetector(
              onTap: () => setState(() => _dest = _Dest.profile),
              child: Padding(
                padding: const EdgeInsets.only(right: 12, left: 4),
                child: _UserChip(user: user),
              ),
            ),
        ],
      ),
      drawer: _AppDrawer(
        user: user,
        selected: _dest,
        unread: _unread,
        onSelect: _select,
        onLogout: _logout,
      ),
      body: _buildBody(),
    );
  }
}

// ---------------------------------------------------------------------------
// Drawer
// ---------------------------------------------------------------------------
class _AppDrawer extends StatelessWidget {
  const _AppDrawer({
    required this.user,
    required this.selected,
    required this.unread,
    required this.onSelect,
    required this.onLogout,
  });

  final CurrentUser? user;
  final _Dest selected;
  final int unread;
  final void Function(_Dest) onSelect;
  final VoidCallback onLogout;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final role = user?.role ?? 'client';

    return Drawer(
      child: Column(
        children: [
          // Header
          DrawerHeader(
            decoration: BoxDecoration(color: colors.bg2),
            margin: EdgeInsets.zero,
            padding: const EdgeInsets.fromLTRB(20, 20, 20, 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                _GradientWordmark(colors: colors),
                const SizedBox(height: 10),
                if (user != null) ...[
                  Text(
                    user!.fullName,
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: colors.text,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  const SizedBox(height: 6),
                  _RoleChip(role: role, colors: colors),
                ],
              ],
            ),
          ),
          // Nav items. overscroll: false убирает stretch-эффект Android 12+,
          // из-за которого выбранный пункт «протекал» к шапке при скролле.
          Expanded(
            child: ScrollConfiguration(
              behavior:
                  ScrollConfiguration.of(context).copyWith(overscroll: false),
              child: ListView(
                padding: const EdgeInsets.symmetric(vertical: 8),
                children: _Dest.values
                    .where((d) => _allowed(role, d))
                    .map((d) => _DrawerTile(
                          dest: d,
                          isSelected: d == selected,
                          unread: d == _Dest.notifications ? unread : 0,
                          onTap: () => onSelect(d),
                          colors: colors,
                          role: role,
                        ))
                    .toList(),
              ),
            ),
          ),
          const Divider(height: 1),
          // Logout
          ListTile(
            leading: Icon(Icons.logout, color: colors.red),
            title: Text('Выйти',
                style: TextStyle(color: colors.red, fontWeight: FontWeight.w600)),
            onTap: onLogout,
          ),
          const SizedBox(height: 8),
        ],
      ),
    );
  }
}

class _DrawerTile extends StatelessWidget {
  const _DrawerTile({
    required this.dest,
    required this.isSelected,
    required this.unread,
    required this.onTap,
    required this.colors,
    this.role,
  });

  final _Dest dest;
  final bool isSelected;
  final int unread;
  final VoidCallback onTap;
  final AppColors colors;
  final String? role;

  @override
  Widget build(BuildContext context) {
    final iconColor = isSelected ? colors.primary : colors.text2;
    final textColor = isSelected ? colors.primary : colors.text;
    // Непрозрачная подсветка: примешиваем primaryDim к фону drawer, чтобы
    // выбранный пункт не «просвечивал» при overscroll-растяжении списка.
    final bgColor = isSelected
        ? Color.alphaBlend(colors.primaryDim, colors.bg2)
        : Colors.transparent;

    Widget icon = Icon(_destIcon(dest), color: iconColor);
    if (dest == _Dest.notifications && unread > 0) {
      icon = Badge(label: Text('$unread'), child: icon);
    }

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 1),
      child: ListTile(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        tileColor: bgColor,
        leading: icon,
        title: Text(
          _destLabel(dest, role),
          style: TextStyle(
            color: textColor,
            fontWeight: isSelected ? FontWeight.w600 : FontWeight.w500,
          ),
        ),
        onTap: onTap,
        dense: true,
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Gradient wordmark (used in DrawerHeader)
// ---------------------------------------------------------------------------
class _GradientWordmark extends StatelessWidget {
  const _GradientWordmark({required this.colors});

  final AppColors colors;

  @override
  Widget build(BuildContext context) {
    return ShaderMask(
      shaderCallback: (bounds) => LinearGradient(
        colors: [colors.primary, colors.accent],
      ).createShader(Rect.fromLTWH(0, 0, bounds.width, bounds.height)),
      child: const Text(
        'СЗТК',
        style: TextStyle(
          fontSize: 22,
          fontWeight: FontWeight.w700,
          letterSpacing: 3,
          color: Colors.white, // masked by shader
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Role chip (used in AppBar and DrawerHeader)
// ---------------------------------------------------------------------------
class _RoleChip extends StatelessWidget {
  const _RoleChip({required this.role, required this.colors});

  final String role;
  final AppColors colors;

  @override
  Widget build(BuildContext context) {
    final color = colors.roleColor(role);
    final label = _roleLabels[role] ?? role;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w600,
          color: color,
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// User chip shown in AppBar actions
// ---------------------------------------------------------------------------
class _UserChip extends StatelessWidget {
  const _UserChip({required this.user});

  final CurrentUser user;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          user.fullName,
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w500,
            color: colors.text2,
          ),
        ),
        const SizedBox(width: 6),
        _RoleChip(role: user.role, colors: colors),
      ],
    );
  }
}
