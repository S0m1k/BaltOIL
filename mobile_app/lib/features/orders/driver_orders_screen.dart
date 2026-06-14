import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/outbox_db.dart';
import '../../core/sync_service.dart';
import 'order_models.dart';
import 'orders_repository.dart';

/// Экран водителя: свои активные заявки + пул свободных.
///
/// Бэк для роли driver отдаёт одним списком свои заявки и свободные new
/// (driver_id IS NULL) — делим на секции на клиенте.
class DriverOrdersScreen extends StatefulWidget {
  const DriverOrdersScreen({super.key, required this.driverId});

  final String driverId;

  @override
  State<DriverOrdersScreen> createState() => _DriverOrdersScreenState();
}

class _DriverOrdersScreenState extends State<DriverOrdersScreen> {
  late Future<List<Order>> _future;
  bool _busy = false;
  int _totalPending = 0;
  // orderId → pending count (для бейджей на карточках)
  final Map<String, int> _pendingByOrder = {};

  @override
  void initState() {
    super.initState();
    _future = OrdersRepository.instance.list();
    // Кэш подписей топлива («ДТ-Л К5» вместо кодов) — как в клиентском списке.
    OrdersRepository.instance.fuelTypes().catchError((_) => <FuelType>[]);
    _loadPendingCounts();
    SyncService.instance.addListener(_onSyncChange);
    // Показывать конфликты, накопленные SyncService.
    SyncService.instance.onConflictsAvailable = _showConflicts;
  }

  @override
  void dispose() {
    SyncService.instance.removeListener(_onSyncChange);
    // Сбрасываем колбэк только если он всё ещё наш.
    SyncService.instance.onConflictsAvailable = null;
    super.dispose();
  }

  Future<void> _loadPendingCounts() async {
    final total = await OutboxDb.instance.totalPending();
    if (!mounted) return;
    setState(() => _totalPending = total);
    // Обновим счётчики по каждому orderId из текущего списка.
    final snap = await _future.catchError((_) => <Order>[]);
    final Map<String, int> counts = {};
    for (final o in snap) {
      final c = await OutboxDb.instance.pendingCountForOrder(o.id);
      if (c > 0) counts[o.id] = c;
    }
    if (mounted) setState(() => _pendingByOrder
      ..clear()
      ..addAll(counts));
  }

  void _onSyncChange() {
    _loadPendingCounts();
    // Перезагружаем список с сервера, чтобы подтянуть актуальные статусы.
    _reload();
  }

  void _showConflicts() {
    final conflicts = SyncService.instance.takeConflicts();
    for (final c in conflicts) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        duration: const Duration(seconds: 6),
        content: Text(
          'Действие не применено — заявку изменил менеджер. '
          '(${c.operation}: ${c.error ?? 'конфликт'})',
        ),
      ));
    }
  }

  Future<void> _reload() async {
    final future = OrdersRepository.instance.list();
    setState(() {
      _future = future;
    });
    await future;
    _loadPendingCounts();
  }

  void _snack(String message) {
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _run(Future<void> Function() action) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await action();
    } catch (e) {
      if (mounted) _snack(apiErrorMessage(e));
    } finally {
      if (mounted) {
        setState(() => _busy = false);
        _reload();
      }
    }
  }

  Future<void> _claim(Order order) => _run(() async {
        await OrdersRepository.instance.claim(order.id);
        if (mounted) _snack('Заявка №${order.orderNumber} принята');
      });

  Future<void> _ack(Order order) => _run(() async {
        await OrdersRepository.instance.ackChanges(order.id);
      });

  Future<void> _deliver(Order order) async {
    // Как на вебе: сначала модалка подтверждения «Отметить доставку».
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Отметить доставку'),
        content: const Text(
            'Подтвердите доставку. Номер ТТН будет присвоен автоматически.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('ОК'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    await _run(() async {
      final delivered = await OrdersRepository.instance.markDelivered(order.id);
      if (!mounted) return;
      _snack('Статус изменён → Доставлена');
      // Д5: фиксация оплаты — только у физлиц; у юрлиц водитель денег не видит.
      if (delivered.isIndividual) {
        await _showPaymentDialog(delivered);
      }
    });
  }

  Future<void> _showPaymentDialog(Order order) async {
    final expected = order.finalAmount ?? order.expectedAmount ?? 0;
    final amountCtrl = TextEditingController(text: expected.toStringAsFixed(0));
    String method = 'cash';
    // Подписи метода — как в селекте веба (promptDriverRecordPayment).
    const methodLabels = {
      'cash': 'Наличные',
      'card': 'Карта',
      'bank_transfer': 'Банковский перевод',
    };

    final confirmed = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Зафиксировать оплату'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(10),
                margin: const EdgeInsets.only(bottom: 16),
                decoration: BoxDecoration(
                  color: const Color(0xFFD97706).withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  '⚠ Сумма к получению: ${expected.toStringAsFixed(0)} ₽',
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                      color: Color(0xFFD97706), fontWeight: FontWeight.w600),
                ),
              ),
              TextField(
                controller: amountCtrl,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Сумма, ₽ *',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                initialValue: method,
                items: [
                  for (final e in methodLabels.entries)
                    DropdownMenuItem(value: e.key, child: Text(e.value)),
                ],
                onChanged: (v) => setDialogState(() => method = v ?? 'cash'),
                decoration: const InputDecoration(
                  labelText: 'Метод оплаты *',
                  border: OutlineInputBorder(),
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(false),
              child: const Text('Отмена'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(context).pop(true),
              child: const Text('ОК'),
            ),
          ],
        ),
      ),
    );

    if (confirmed != true) return;
    final amount = double.tryParse(amountCtrl.text.replaceAll(',', '.'));
    if (amount == null || amount <= 0) {
      _snack('Некорректная сумма — оплата не записана');
      return;
    }
    try {
      await OrdersRepository.instance
          .recordPayment(orderId: order.id, amount: amount, method: method);
      if (mounted) _snack('Оплата зафиксирована');
    } catch (e) {
      if (mounted) _snack(apiErrorMessage(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        // Глобальный индикатор офлайн-очереди (показывается только при наличии).
        if (_totalPending > 0)
          Material(
            color: const Color(0xFFD97706).withValues(alpha: 0.12),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
              child: Row(
                children: [
                  const Icon(Icons.cloud_off, size: 16, color: Color(0xFFD97706)),
                  const SizedBox(width: 8),
                  Text(
                    'Не синхронизировано: $_totalPending',
                    style: const TextStyle(
                        fontSize: 13, color: Color(0xFFD97706)),
                  ),
                ],
              ),
            ),
          ),
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
                  return ListView(children: [
                    const SizedBox(height: 120),
                    Center(child: Text(apiErrorMessage(snap.error!))),
                    Center(
                        child: OutlinedButton(
                            onPressed: _reload,
                            child: const Text('Повторить'))),
                  ]);
                }
                final orders = snap.data ?? const [];
                final mineActive = orders
                    .where((o) =>
                        o.driverId == widget.driverId &&
                        o.status == 'accepted')
                    .toList();
                final pool = orders
                    .where((o) => o.status == 'new' && o.driverId == null)
                    .toList();
                final mineDone = orders
                    .where((o) =>
                        o.driverId == widget.driverId &&
                        o.status == 'delivered')
                    .toList();

                if (orders.isEmpty) {
                  return ListView(children: const [
                    SizedBox(height: 120),
                    Center(child: Text('Заявок нет')),
                  ]);
                }

                return ListView(
                  children: [
                    if (mineActive.isNotEmpty) ...[
                      const _SectionHeader('В работе'),
                      for (final o in mineActive)
                        _DriverOrderCard(
                          order: o,
                          busy: _busy,
                          pendingCount: _pendingByOrder[o.id] ?? 0,
                          onAck: o.pendingDriverAck ? () => _ack(o) : null,
                          onDeliver: () => _deliver(o),
                        ),
                    ],
                    if (pool.isNotEmpty) ...[
                      const _SectionHeader('Свободные заявки'),
                      for (final o in pool)
                        _DriverOrderCard(
                          order: o,
                          busy: _busy,
                          pendingCount: 0,
                          onClaim: () => _claim(o),
                        ),
                    ],
                    if (mineDone.isNotEmpty) ...[
                      const _SectionHeader('Доставленные'),
                      for (final o in mineDone)
                        _DriverOrderCard(
                          order: o,
                          busy: _busy,
                          pendingCount: _pendingByOrder[o.id] ?? 0,
                          // Д5: оплату можно внести и после доставки.
                          onRecordPayment:
                              o.isIndividual && o.paymentStatus != 'paid'
                                  ? () =>
                                      _showPaymentDialog(o).then((_) => _reload())
                                  : null,
                        ),
                    ],
                    const SizedBox(height: 80),
                  ],
                );
              },
            ),
          ),
        ),
      ],
    );
  }
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader(this.title);

  final String title;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
      child: Text(title, style: Theme.of(context).textTheme.titleMedium),
    );
  }
}

class _DriverOrderCard extends StatelessWidget {
  const _DriverOrderCard({
    required this.order,
    required this.busy,
    required this.pendingCount,
    this.onClaim,
    this.onDeliver,
    this.onAck,
    this.onRecordPayment,
  });

  final Order order;
  final bool busy;
  final int pendingCount; // число офлайн-действий в очереди для этой заявки
  final VoidCallback? onClaim;
  final VoidCallback? onDeliver;
  final VoidCallback? onAck;
  final VoidCallback? onRecordPayment;

  @override
  Widget build(BuildContext context) {
    // Деньги показываем только по физлицам (Д5: у юрлиц водитель денег не видит).
    final showMoney = order.isIndividual;
    final amount = order.finalAmount ?? order.expectedAmount;

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    '№${order.orderNumber} — ${FuelCatalog.label(order.fuelType)}, '
                    '${order.volumeRequested.toStringAsFixed(0)} л',
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                ),
                if (pendingCount > 0)
                  Padding(
                    padding: const EdgeInsets.only(right: 6),
                    child: Tooltip(
                      message: 'Не синхронизировано: $pendingCount',
                      child: const Icon(Icons.cloud_off,
                          size: 16, color: Color(0xFFD97706)),
                    ),
                  ),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: Color(orderStatusColors[order.status] ?? 0xFF6B7280)
                        .withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text(
                    orderStatusLabel(order.status),
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color:
                          Color(orderStatusColors[order.status] ?? 0xFF6B7280),
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(order.deliveryAddress),
            if (order.desiredDate != null)
              Text(
                  'Желаемая дата: ${order.desiredDate!.day}.${order.desiredDate!.month}.${order.desiredDate!.year}',
                  style: Theme.of(context).textTheme.bodySmall),
            if (showMoney && amount != null)
              Text('К оплате: ${amount.toStringAsFixed(0)} ₽',
                  style: Theme.of(context).textTheme.bodySmall),
            if (order.managerComment?.isNotEmpty == true)
              Text('Менеджер: ${order.managerComment}',
                  style: Theme.of(context).textTheme.bodySmall),
            if (order.pendingDriverAck)
              Container(
                margin: const EdgeInsets.only(top: 8),
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: Colors.orange.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.warning_amber, size: 18, color: Colors.orange),
                    const SizedBox(width: 8),
                    const Expanded(child: Text('Менеджер изменил заявку')),
                    TextButton(
                      onPressed: busy ? null : onAck,
                      child: const Text('Ознакомлен'),
                    ),
                  ],
                ),
              ),
            if (onClaim != null || onDeliver != null || onRecordPayment != null)
              Align(
                alignment: Alignment.centerRight,
                child: Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: switch ((onClaim, onDeliver)) {
                    (final claim?, _) => FilledButton.icon(
                        onPressed: busy ? null : claim,
                        icon: const Icon(Icons.front_hand, size: 18),
                        label: const Text('Взять заявку'),
                      ),
                    (_, final deliver?) => FilledButton.icon(
                        onPressed: busy ? null : deliver,
                        icon: const Icon(Icons.check, size: 18),
                        label: const Text('Доставлена'),
                      ),
                    _ => OutlinedButton.icon(
                        onPressed: busy ? null : onRecordPayment,
                        icon: const Icon(Icons.payments_outlined, size: 18),
                        label: const Text('Принять оплату'),
                      ),
                  },
                ),
              ),
          ],
        ),
      ),
    );
  }
}
