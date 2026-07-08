import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/theme.dart';
import '../auth/auth_repository.dart';
import 'order_create_screen.dart';
import 'order_detail_screen.dart';
import 'order_models.dart';
import 'orders_repository.dart';

// Web sub-tab order: Все / Новые / На согласовании / Ждут доставки /
// Доставленные / Отменённые.
// null = «Все», non-null = status key.
const _kFilterTabs = <({String? status, String label})>[
  (status: null, label: 'Все'),
  (status: 'new', label: 'Новые'),
  (status: 'awaiting_manager', label: 'На согласовании'),
  (status: 'accepted', label: 'Ждут доставки'),
  (status: 'delivered', label: 'Доставленные'),
  (status: 'cancelled', label: 'Отменённые'),
];

class OrdersScreen extends StatefulWidget {
  const OrdersScreen({super.key, this.canCreate = true, this.user});

  /// Создавать заявки могут клиенты; водителю кнопка не нужна.
  final bool canCreate;

  /// Текущий пользователь (нужен для перехода в детали заявки).
  /// Если не передан — загружается лениво при первом нажатии на плитку.
  final CurrentUser? user;

  @override
  State<OrdersScreen> createState() => _OrdersScreenState();
}

class _OrdersScreenState extends State<OrdersScreen> {
  late Future<List<Order>> _future;
  CurrentUser? _user;

  /// null = «Все».
  String? _selectedStatus;

  @override
  void initState() {
    super.initState();
    _user = widget.user;
    _future = OrdersRepository.instance.list();
    // Прогреваем кэш подписей топлива, чтобы списки показывали «ДТ-Л К5»,
    // а не diesel_summer. Ошибка не критична — останутся фолбэк-подписи.
    OrdersRepository.instance.fuelTypes().catchError((_) => <FuelType>[]);
    if (_user == null) {
      AuthRepository.instance.me().then((u) {
        if (mounted) setState(() => _user = u);
      }).catchError((_) {});
    }
  }

  Future<void> _reload() async {
    final future = OrdersRepository.instance.list();
    setState(() {
      _future = future;
    });
    await future;
  }

  Future<void> _create() async {
    var user = _user;
    user ??= await AuthRepository.instance.me();
    if (!mounted) return;
    final created = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => OrderCreateScreen(user: user!)),
    );
    if (created == true) _reload();
  }

  bool _isDriverRole() => _user?.role == 'driver' || widget.user?.role == 'driver';

  List<({String? status, String label})> _visibleTabs() {
    if (!_isDriverRole()) return _kFilterTabs;
    return _kFilterTabs
        .where((t) => t.status != 'awaiting_manager')
        .toList();
  }

  List<Order> _applyFilter(List<Order> orders) {
    if (_selectedStatus == null) return orders;
    return orders.where((o) => o.status == _selectedStatus).toList();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final tabs = _visibleTabs();

    // Guard: if the selected status was hidden (driver role set after load),
    // reset to «Все».
    if (_selectedStatus != null &&
        !tabs.any((t) => t.status == _selectedStatus)) {
      _selectedStatus = null;
    }

    return Scaffold(
      floatingActionButton: widget.canCreate
          ? FloatingActionButton.extended(
              onPressed: _create,
              icon: const Icon(Icons.add),
              label: const Text('Заявка'),
            )
          : null,
      body: Column(
        children: [
          // ── Status filter row ──────────────────────────────────────────
          _StatusFilterRow(
            tabs: tabs,
            selectedStatus: _selectedStatus,
            colors: colors,
            onSelected: (status) => setState(() => _selectedStatus = status),
          ),
          // ── Orders list ───────────────────────────────────────────────
          Expanded(
            child: RefreshIndicator(
              onRefresh: _reload,
              child: FutureBuilder<List<Order>>(
                future: _future,
                builder: (context, snap) {
                  if (snap.connectionState != ConnectionState.done) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  if (snap.hasError) {
                    return _ErrorRetry(
                        message: apiErrorMessage(snap.error!),
                        onRetry: _reload);
                  }
                  final allOrders = snap.data ?? const [];
                  final orders = _applyFilter(allOrders);

                  if (orders.isEmpty) {
                    final isEmpty = allOrders.isEmpty;
                    return ListView(children: [
                      const SizedBox(height: 120),
                      Center(
                        child: Text(
                          isEmpty
                              ? 'Заявок пока нет'
                              : 'Нет заявок с таким статусом',
                          style: TextStyle(color: colors.text2),
                        ),
                      ),
                    ]);
                  }
                  return ListView.separated(
                    itemCount: orders.length,
                    separatorBuilder: (_, _) => const Divider(height: 1),
                    itemBuilder: (context, i) =>
                        _OrderTile(order: orders[i], user: _user),
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

// ── Status filter row widget ──────────────────────────────────────────────────

class _StatusFilterRow extends StatelessWidget {
  const _StatusFilterRow({
    required this.tabs,
    required this.selectedStatus,
    required this.colors,
    required this.onSelected,
  });

  final List<({String? status, String label})> tabs;
  final String? selectedStatus;
  final AppColors colors;
  final ValueChanged<String?> onSelected;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: colors.bg2,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            child: Row(
              children: tabs.map((tab) {
                final isActive = selectedStatus == tab.status;
                return Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ChoiceChip(
                    label: Text(tab.label),
                    selected: isActive,
                    onSelected: (_) => onSelected(tab.status),
                    selectedColor: colors.primary,
                    backgroundColor: colors.bg,
                    side: BorderSide(
                      color: isActive ? colors.primary : colors.border,
                    ),
                    labelStyle: TextStyle(
                      color: isActive ? Colors.white : colors.text2,
                      fontWeight:
                          isActive ? FontWeight.w600 : FontWeight.normal,
                      fontSize: 13,
                    ),
                    showCheckmark: false,
                    padding: const EdgeInsets.symmetric(horizontal: 4),
                  ),
                );
              }).toList(),
            ),
          ),
          Divider(height: 1, color: colors.border),
        ],
      ),
    );
  }
}

// ── Order tile ────────────────────────────────────────────────────────────────

class _OrderTile extends StatelessWidget {
  const _OrderTile({required this.order, this.user});

  final Order order;
  final CurrentUser? user;

  Color _statusColor(BuildContext context) {
    final hex = orderStatusColors[order.status];
    return hex != null ? Color(hex) : Theme.of(context).colorScheme.primary;
  }

  @override
  Widget build(BuildContext context) {
    final amount = order.expectedAmount;
    return ListTile(
      onTap: user == null
          ? null
          : () => Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) =>
                      OrderDetailScreen(orderId: order.id, user: user!),
                ),
              ),
      title: Text('№${order.orderNumber} — ${FuelCatalog.label(order.fuelType)}, '
          '${order.volumeRequested.toStringAsFixed(0)} л'),
      // Как на вебе (d29807a): имя организации/клиента жирным перед адресом.
      subtitle: order.buyerName == null
          ? Text(order.deliveryAddress,
              maxLines: 1, overflow: TextOverflow.ellipsis)
          : Text.rich(
              TextSpan(children: [
                TextSpan(
                  text: order.buyerName,
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
                TextSpan(text: ' · ${order.deliveryAddress}'),
              ]),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
      trailing: Column(
        crossAxisAlignment: CrossAxisAlignment.end,
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
            decoration: BoxDecoration(
              color: _statusColor(context).withValues(alpha: 0.15),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Text(orderStatusLabel(order.status),
                style: TextStyle(
                    fontSize: 12,
                    color: _statusColor(context),
                    fontWeight: FontWeight.w600)),
          ),
          if (amount != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text('${amount.toStringAsFixed(0)} ₽',
                  style: Theme.of(context).textTheme.bodySmall),
            ),
        ],
      ),
    );
  }
}

// ── Error / retry ─────────────────────────────────────────────────────────────

class _ErrorRetry extends StatelessWidget {
  const _ErrorRetry({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return ListView(children: [
      const SizedBox(height: 120),
      Center(child: Text(message, textAlign: TextAlign.center)),
      const SizedBox(height: 12),
      Center(
          child:
              OutlinedButton(onPressed: onRetry, child: const Text('Повторить'))),
    ]);
  }
}
