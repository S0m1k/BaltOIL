import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../auth/auth_repository.dart';
import 'order_create_screen.dart';
import 'order_detail_screen.dart';
import 'order_models.dart';
import 'orders_repository.dart';

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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      floatingActionButton: widget.canCreate
          ? FloatingActionButton.extended(
              onPressed: _create,
              icon: const Icon(Icons.add),
              label: const Text('Заявка'),
            )
          : null,
      body: RefreshIndicator(
        onRefresh: _reload,
        child: FutureBuilder<List<Order>>(
          future: _future,
          builder: (context, snap) {
            if (snap.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snap.hasError) {
              return _ErrorRetry(
                  message: apiErrorMessage(snap.error!), onRetry: _reload);
            }
            final orders = snap.data ?? const [];
            if (orders.isEmpty) {
              return ListView(children: const [
                SizedBox(height: 120),
                Center(child: Text('Заявок пока нет')),
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
    );
  }
}

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
      subtitle: Text(order.deliveryAddress,
          maxLines: 1, overflow: TextOverflow.ellipsis),
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
