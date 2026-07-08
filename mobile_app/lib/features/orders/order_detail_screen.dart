import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/api_client.dart';
import '../../core/theme.dart';
import '../auth/auth_repository.dart';
import '../common/copyable_phone.dart';
import 'order_create_screen.dart';
import 'order_models.dart';
import 'orders_repository.dart';

// ---------------------------------------------------------------------------
// Constants mirrored from web frontend
// ---------------------------------------------------------------------------

const _kPaymentLabels = <String, String>{
  'prepaid': 'Предоплата',
  'on_delivery': 'По факту (при прибытии)',
  'trade_credit': 'Товарный кредит',
  'postpaid': 'Постоплата (по счёту)',
  'debt': 'В долг',
};

// Единый счёт (веб 4710): исторические preliminary/final тоже показываем «Счёт».
const _kDocTypeLabels = <String, String>{
  'invoice': 'Счёт',
  'invoice_preliminary': 'Счёт',
  'invoice_final': 'Счёт',
  'ttn': 'ТТН',
  'upd': 'УПД',
  'poa': 'Доверенность',
};

const _kDocStatusLabels = <String, String>{
  'draft': 'Черновик',
  'ready': 'Готов',
  'sent': 'Отправлен',
  'cancelled': 'Аннулирован',
};

const _kChangedFieldLabels = <String, String>{
  'desired_date': 'дата',
  'volume': 'объём',
  'fuel_type': 'топливо',
  'address': 'адрес',
  'comment': 'комментарий',
  'driver': 'водитель',
  'amount': 'сумма',
};

const _kRoleLabels = <String, String>{
  'admin': 'Админ',
  'manager': 'Менеджер',
  'driver': 'Водитель',
  'client': 'Клиент',
};

// ---------------------------------------------------------------------------
// OrderDetailScreen
// ---------------------------------------------------------------------------

class OrderDetailScreen extends StatefulWidget {
  const OrderDetailScreen({
    super.key,
    required this.orderId,
    required this.user,
  });

  final String orderId;
  final CurrentUser user;

  @override
  State<OrderDetailScreen> createState() => _OrderDetailScreenState();
}

class _OrderDetailScreenState extends State<OrderDetailScreen> {
  late Future<OrderDetail> _future;
  Future<List<OrderDocument>>? _docsFuture;
  bool _busy = false;

  bool get _isStaff =>
      widget.user.role == 'manager' || widget.user.role == 'admin';

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    final f = OrdersRepository.instance.getDetail(widget.orderId);
    setState(() {
      _future = f;
      if (_isStaff) {
        _docsFuture =
            OrdersRepository.instance.listDocuments(widget.orderId);
      }
    });
  }

  void _reload() => _load();

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _run(Future<void> Function() action) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await action();
    } on Exception catch (e) {
      if (mounted) _snack(apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // ── Actions ──────────────────────────────────────────────────────────────

  Future<void> _approve(OrderDetail order) => _run(() async {
        await OrdersRepository.instance.transition(
          order.id,
          'new',
          comment: 'Заявка согласована менеджером',
        );
        _reload();
      });

  Future<void> _cancelOrder(OrderDetail order) async {
    final commentCtrl = TextEditingController();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Отменить заявку'),
        content: TextField(
          controller: commentCtrl,
          decoration: const InputDecoration(
            labelText: 'Причина отмены (необязательно)',
            border: OutlineInputBorder(),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Нет'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Отменить'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    await _run(() async {
      await OrdersRepository.instance.transition(
        order.id,
        'cancelled',
        comment:
            commentCtrl.text.isNotEmpty ? commentCtrl.text : null,
      );
      _reload();
    });
  }

  Future<void> _reschedule(OrderDetail order) async {
    DateTime? picked;
    final now = DateTime.now();
    picked = await showDatePicker(
      context: context,
      initialDate: order.desiredDate ?? now,
      firstDate: now,
      lastDate: now.add(const Duration(days: 365)),
      helpText: 'Выберите новую дату',
    );
    if (picked == null) return;
    await _run(() async {
      await OrdersRepository.instance
          .reschedule(order.id, desiredDate: picked);
      _reload();
    });
  }

  Future<void> _recordPaymentManager(OrderDetail order) async {
    final debtAmount = order.debtAmount;
    final amountCtrl =
        TextEditingController(text: debtAmount.toStringAsFixed(0));
    String method = 'cash';
    const methodLabels = {
      'cash': 'Наличные',
      'card': 'Карта',
      'bank_transfer': 'Банковский перевод',
    };
    final confirmed = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          title: const Text('Зафиксировать оплату'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (debtAmount > 0)
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(10),
                  margin: const EdgeInsets.only(bottom: 16),
                  decoration: BoxDecoration(
                    color:
                        const Color(0xFFD97706).withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    'Долг: ${debtAmount.toStringAsFixed(2)} ₽',
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      color: Color(0xFFD97706),
                      fontWeight: FontWeight.w600,
                    ),
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
                    DropdownMenuItem(
                      value: e.key,
                      child: Text(e.value),
                    ),
                ],
                onChanged: (v) =>
                    setDialogState(() => method = v ?? 'cash'),
                decoration: const InputDecoration(
                  labelText: 'Метод оплаты *',
                  border: OutlineInputBorder(),
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: const Text('Отмена'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(ctx).pop(true),
              child: const Text('Зафиксировать'),
            ),
          ],
        ),
      ),
    );
    if (confirmed != true) return;
    final amount =
        double.tryParse(amountCtrl.text.replaceAll(',', '.'));
    if (amount == null || amount <= 0) {
      _snack('Некорректная сумма — оплата не записана');
      return;
    }
    await _run(() async {
      await OrdersRepository.instance.recordPaymentManager(
        orderId: order.id,
        amount: amount,
        method: method,
      );
      _snack('Оплата зафиксирована');
      _reload();
    });
  }

  // Driver actions (reusing same repo calls as driver_orders_screen)

  Future<void> _driverClaim(OrderDetail order) => _run(() async {
        await OrdersRepository.instance.claim(order.id);
        _snack('Заявка №${order.orderNumber} принята');
        _reload();
      });

  Future<void> _driverAccept(OrderDetail order) => _run(() async {
        await OrdersRepository.instance.accept(order.id);
        _snack('Заявка принята');
        _reload();
      });

  Future<void> _driverAck(OrderDetail order) => _run(() async {
        await OrdersRepository.instance.ackChanges(order.id);
        _snack('Изменения подтверждены');
        _reload();
      });

  Future<void> _driverDeliver(OrderDetail order) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Отметить доставку'),
        content: const Text(
          'Подтвердите доставку. '
          'Номер ТТН будет присвоен автоматически.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('ОК'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    await _run(() async {
      final delivered =
          await OrdersRepository.instance.markDelivered(order.id);
      if (!mounted) return;
      _snack('Статус изменён → Доставлена');
      if (delivered.isIndividual) {
        await _showDriverPaymentDialog(delivered);
      }
      _reload();
    });
  }

  Future<void> _showDriverPaymentDialog(Order order) async {
    final expected = order.finalAmount ?? order.expectedAmount ?? 0;
    final amountCtrl =
        TextEditingController(text: expected.toStringAsFixed(0));
    String method = 'cash';
    const methodLabels = {
      'cash': 'Наличные',
      'card': 'Карта',
      'bank_transfer': 'Банковский перевод',
    };
    final confirmed = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
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
                  'Сумма к получению: ${expected.toStringAsFixed(0)} ₽',
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    color: Color(0xFFD97706),
                    fontWeight: FontWeight.w600,
                  ),
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
                    DropdownMenuItem(
                      value: e.key,
                      child: Text(e.value),
                    ),
                ],
                onChanged: (v) =>
                    setDialogState(() => method = v ?? 'cash'),
                decoration: const InputDecoration(
                  labelText: 'Метод оплаты *',
                  border: OutlineInputBorder(),
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: const Text('Отмена'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(ctx).pop(true),
              child: const Text('ОК'),
            ),
          ],
        ),
      ),
    );
    if (confirmed != true) return;
    final amount =
        double.tryParse(amountCtrl.text.replaceAll(',', '.'));
    if (amount == null || amount <= 0) {
      _snack('Некорректная сумма — оплата не записана');
      return;
    }
    try {
      await OrdersRepository.instance.recordPayment(
        orderId: order.id,
        amount: amount,
        method: method,
      );
      if (mounted) _snack('Оплата зафиксирована');
    } on Exception catch (e) {
      if (mounted) _snack(apiErrorMessage(e));
    }
  }

  // ── Build ─────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Scaffold(
      backgroundColor: c.bg,
      appBar: AppBar(
        backgroundColor: c.bg,
        title: const Text('Заявка'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: 'Обновить',
            onPressed: _busy ? null : _reload,
          ),
        ],
      ),
      body: FutureBuilder<OrderDetail>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      apiErrorMessage(snap.error!),
                      textAlign: TextAlign.center,
                      style: TextStyle(color: c.red),
                    ),
                    const SizedBox(height: 16),
                    OutlinedButton(
                      onPressed: _reload,
                      child: const Text('Повторить'),
                    ),
                  ],
                ),
              ),
            );
          }
          final order = snap.data!;
          return _buildBody(context, order, c);
        },
      ),
    );
  }

  Widget _buildBody(
    BuildContext context,
    OrderDetail order,
    AppColors c,
  ) {
    return RefreshIndicator(
      onRefresh: () async => _reload(),
      child: ListView(
        padding: const EdgeInsets.fromLTRB(12, 12, 12, 80),
        children: [
          _buildHeader(context, order, c),
          const SizedBox(height: 12),
          _buildDetailsGrid(context, order, c),
          const SizedBox(height: 12),
          _buildPaymentSummary(context, order, c),
          const SizedBox(height: 12),
          _buildActionBar(context, order, c),
          const SizedBox(height: 16),
          _buildTimeline(context, order, c),
          if (_isStaff) ...[
            const SizedBox(height: 16),
            _buildDocuments(context, order, c),
          ],
        ],
      ),
    );
  }

  // ── Header (order number + status chip) ──────────────────────────────────

  Widget _buildHeader(
    BuildContext context,
    OrderDetail order,
    AppColors c,
  ) {
    final statusColor = c.statusColor(order.status);
    final label = kStatusLabels[order.status] ?? order.status;
    return Row(
      children: [
        Expanded(
          child: Text(
            'Заявка №${order.orderNumber}',
            style: TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w700,
              color: c.text,
            ),
          ),
        ),
        _StatusBadge(label: label, color: statusColor),
      ],
    );
  }

  // ── Details grid ─────────────────────────────────────────────────────────

  Widget _buildDetailsGrid(
    BuildContext context,
    OrderDetail order,
    AppColors c,
  ) {
    final isDriver = widget.user.role == 'driver';
    final driverHidesMoney =
        isDriver && order.orderKind != 'individual';

    final rows = <_DetailRow>[];

    if (_isStaff) {
      rows.add(_DetailRow(
        label: 'ID заявки',
        child: _UuidCell(value: order.id, onSnack: _snack),
      ));
      if (order.clientId != null) {
        rows.add(_DetailRow(
          label: 'Клиент (ID)',
          child:
              _UuidCell(value: order.clientId!, onSnack: _snack),
        ));
      }
    }

    // Заказчик — имя организации/клиента, как на вебе (d29807a).
    if (order.buyerName != null || _isStaff) {
      rows.add(_DetailRow(
        label: 'Заказчик',
        text: order.buyerName ?? 'Физлицо',
      ));
    }

    rows.add(_DetailRow(
      label: 'Топливо',
      text: FuelCatalog.label(order.fuelType),
    ));

    rows.add(_DetailRow(
      label: 'Объём заказан',
      text:
          '${_fmtNum(order.volumeRequested)} л',
    ));

    if (order.volumeDelivered != null) {
      rows.add(_DetailRow(
        label: 'Объём доставлен',
        text: '${_fmtNum(order.volumeDelivered!)} л',
      ));
    }

    rows.add(_DetailRow(
      label: 'Адрес доставки',
      text: order.deliveryAddress,
    ));

    if (order.deliveryZoneName != null &&
        order.deliveryZoneName!.isNotEmpty) {
      rows.add(_DetailRow(
        label: 'Зона доставки',
        text: order.deliveryZoneName!,
      ));
    }

    if (order.deliveryCost != null) {
      rows.add(_DetailRow(
        label: 'Стоимость доставки',
        text: '${_fmtNum(order.deliveryCost!)} ₽',
      ));
    }

    rows.add(_DetailRow(
      label: 'Желаемая дата',
      text: order.desiredDate != null
          ? _fmtDate(order.desiredDate!)
          : '—',
    ));

    if (order.contactPersonName != null ||
        order.contactPersonPhone != null) {
      rows.add(_DetailRow(
        label: 'Контакт для приёмки',
        child: _ContactCell(
          name: order.contactPersonName,
          phone: order.contactPersonPhone,
          accentColor: c.accent,
          onSnack: _snack,
        ),
      ));
    }

    if (_isStaff && order.ttnNumber != null) {
      rows.add(_DetailRow(
        label: 'Номер ТТН',
        child: Text(
          order.ttnNumber!,
          style: const TextStyle(fontFamily: 'monospace'),
        ),
      ));
    }

    if (!driverHidesMoney && order.paymentType != null) {
      rows.add(_DetailRow(
        label: 'Оплата',
        text: _kPaymentLabels[order.paymentType!] ??
            order.paymentType!,
      ));
    }

    if (!driverHidesMoney &&
        (order.expectedAmount != null || order.finalAmount != null)) {
      final parts = <String>[];
      if (order.expectedAmount != null) {
        parts.add(
            'Ожидалось: ${_fmtMoney(order.expectedAmount!)} ₽');
      }
      if (order.finalAmount != null) {
        parts.add('Факт: ${_fmtMoney(order.finalAmount!)} ₽');
      }
      rows.add(_DetailRow(
        label: 'Суммы',
        text: parts.join('  '),
      ));
    }

    if (_isStaff && order.driverId != null) {
      rows.add(_DetailRow(
        label: 'Водитель (ID)',
        child:
            _UuidCell(value: order.driverId!, onSnack: _snack),
      ));
    }

    if (order.clientComment?.isNotEmpty == true) {
      rows.add(_DetailRow(
        label: 'Комментарий клиента',
        text: order.clientComment!,
      ));
    }

    if (order.managerComment?.isNotEmpty == true) {
      rows.add(_DetailRow(
        label: 'Комментарий менеджера',
        text: order.managerComment!,
      ));
    }

    if (order.rejectionReason?.isNotEmpty == true) {
      rows.add(_DetailRow(
        label: 'Причина отклонения',
        child: Text(
          order.rejectionReason!,
          style: TextStyle(color: c.red),
        ),
      ));
    }

    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: rows
            .map((r) => _DetailsGridRow(row: r, colors: c))
            .toList(),
      ),
    );
  }

  // ── Payment summary ───────────────────────────────────────────────────────

  Widget _buildPaymentSummary(
    BuildContext context,
    OrderDetail order,
    AppColors c,
  ) {
    final isDriver = widget.user.role == 'driver';
    if (isDriver && order.orderKind != 'individual') {
      return const SizedBox.shrink();
    }

    final target = order.finalAmount ?? order.expectedAmount;
    final paid = order.paidTotal;
    final debt = order.debtAmount;
    final ps = order.paymentStatus;
    final isPaid = ps == 'paid' || ps == 'overpaid';
    final psLabel = isPaid ? 'Оплачено' : 'Не оплачено';
    final psColor = isPaid ? c.green : c.red;

    final isClient = widget.user.role == 'client';
    final showUnpaidAlert = isClient &&
        !isPaid &&
        !order.allowDeliveryUnpaid &&
        order.orderKind != 'ttn_l' &&
        order.status != 'cancelled';

    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Wrap(
                  spacing: 18,
                  runSpacing: 4,
                  children: [
                    _MoneyChip(
                      label: 'Ожидается',
                      value: target != null
                          ? '${_fmtMoney(target)} ₽'
                          : '—',
                      colors: c,
                    ),
                    _MoneyChip(
                      label: 'Оплачено',
                      value: '${_fmtMoney(paid)} ₽',
                      valueColor: paid > 0 ? c.green : null,
                      colors: c,
                    ),
                    _MoneyChip(
                      label: 'Долг',
                      value: '${_fmtMoney(debt)} ₽',
                      valueColor: debt > 0 ? c.red : null,
                      colors: c,
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  border: Border.all(color: psColor),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(
                  psLabel,
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: psColor,
                  ),
                ),
              ),
            ],
          ),
          if (order.pricingWarning) ...[
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: c.primary.withValues(alpha: 0.08),
                border: Border.all(color: c.primary),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Row(
                children: [
                  Icon(Icons.warning_rounded, size: 14, color: c.primary),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      'Сумма не определена — назначьте тариф для клиента.',
                      style: TextStyle(fontSize: 12, color: c.primary),
                    ),
                  ),
                ],
              ),
            ),
          ],
          if (showUnpaidAlert) ...[
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: c.red.withValues(alpha: 0.06),
                border: Border.all(color: c.red.withValues(alpha: 0.4)),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Row(
                children: [
                  Icon(Icons.warning_rounded, size: 16, color: c.red),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Заявку необходимо оплатить. Свяжитесь с менеджером.',
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                        color: c.red,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  // ── Action bar ───────────────────────────────────────────────────────────

  Widget _buildActionBar(
    BuildContext context,
    OrderDetail order,
    AppColors c,
  ) {
    final role = widget.user.role;
    final s = order.status;
    final btns = <Widget>[];

    // Ack banner for driver
    Widget? ackBanner;
    if (role == 'driver' && order.pendingDriverAck) {
      final fields = order.pendingChangedFields
          .map((k) => _kChangedFieldLabels[k] ?? k)
          .join(', ');
      final whatText = fields.isNotEmpty ? ' Изменено: $fields.' : '';
      ackBanner = Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: c.primary.withValues(alpha: 0.10),
          border: Border.all(color: c.primary),
          borderRadius: BorderRadius.circular(6),
        ),
        child: Row(
          children: [
            Icon(Icons.warning_rounded, size: 16, color: c.primary),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                'Заявка изменена — подтвердите получение изменений.$whatText',
                style: TextStyle(fontSize: 12, color: c.primary),
              ),
            ),
            const SizedBox(width: 8),
            TextButton(
              onPressed: _busy ? null : () => _driverAck(order),
              child: const Text('Подтвердить'),
            ),
          ],
        ),
      );
    }

    // Manager / admin buttons
    if (role == 'manager' || role == 'admin') {
      if (s == 'awaiting_manager') {
        btns.add(_ActionBtn(
          label: 'Согласовать',
          icon: Icons.check,
          color: c.green,
          onTap: _busy ? null : () => _approve(order),
        ));
      }
      if (s == 'new' || s == 'accepted' || s == 'awaiting_manager') {
        btns.add(_ActionBtn(
          label: 'Отменить',
          icon: Icons.close,
          color: c.red,
          onTap: _busy ? null : () => _cancelOrder(order),
        ));
      }
      if (s == 'new' || s == 'accepted') {
        btns.add(_ActionBtn(
          label: 'Перенести',
          icon: Icons.calendar_month,
          color: c.text2,
          onTap: _busy ? null : () => _reschedule(order),
        ));
      }
      final ps = order.paymentStatus;
      final isPaid = ps == 'paid' || ps == 'overpaid';
      if (s != 'cancelled' && !isPaid) {
        btns.add(_ActionBtn(
          label: 'Зафиксировать оплату',
          icon: Icons.account_balance_wallet_outlined,
          color: c.green,
          onTap: _busy
              ? null
              : () => _recordPaymentManager(order),
        ));
      }
      // Дублировать (веб F1, 2026-06-24): открыть форму создания с
      // предзаполненными полями — например, разбить заявку >3000 л на две.
      btns.add(_ActionBtn(
        label: 'Дублировать',
        icon: Icons.copy,
        color: c.text2,
        onTap: _busy
            ? null
            : () async {
                final created = await Navigator.of(context).push<bool>(
                  MaterialPageRoute(
                    builder: (_) => OrderCreateScreen(
                        user: widget.user, duplicateFrom: order),
                  ),
                );
                if (created == true && mounted) _reload();
              },
      ));
    }

    // Driver buttons
    if (role == 'driver') {
      if (s == 'new' && order.driverId == null) {
        btns.add(_ActionBtn(
          label: 'Взять заявку',
          icon: Icons.front_hand,
          color: c.accent,
          onTap: _busy ? null : () => _driverClaim(order),
        ));
      }
      if (s == 'new' && order.driverId == widget.user.id) {
        btns.add(_ActionBtn(
          label: 'Принять',
          icon: Icons.check,
          color: c.accent,
          onTap: _busy ? null : () => _driverAccept(order),
        ));
      }
      if (s == 'accepted' && order.driverId == widget.user.id) {
        btns.add(_ActionBtn(
          label: 'Доставлена',
          icon: Icons.local_shipping,
          color: c.primary,
          onTap: _busy ? null : () => _driverDeliver(order),
        ));
      }
      if (s == 'new' || s == 'accepted') {
        btns.add(_ActionBtn(
          label: 'Перенести дату',
          icon: Icons.calendar_month,
          color: c.text2,
          onTap: _busy ? null : () => _reschedule(order),
        ));
      }
      // Individual: can-deliver hint
      if (order.orderKind == 'individual' &&
          (s == 'new' || s == 'accepted')) {
        final ps = order.paymentStatus;
        final canDeliver = (ps == 'paid' || ps == 'overpaid') ||
            order.allowDeliveryUnpaid;
        if (canDeliver) {
          btns.add(Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.check_circle_outline, size: 14, color: c.green),
              const SizedBox(width: 4),
              Text(
                'Можно доставлять',
                style: TextStyle(fontSize: 12, color: c.green),
              ),
            ],
          ));
        }
      }
    }

    // Client buttons
    if (role == 'client') {
      if (s == 'awaiting_manager') {
        btns.add(Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.access_time, size: 13, color: c.primary),
            const SizedBox(width: 4),
            Flexible(
              child: Text(
                'Объём ≥ 3000 л — на согласовании',
                style: TextStyle(fontSize: 12, color: c.primary),
              ),
            ),
          ],
        ));
      }
      if (s == 'new' || s == 'accepted' || s == 'awaiting_manager') {
        btns.add(_ActionBtn(
          label: 'Перенести дату',
          icon: Icons.calendar_month,
          color: c.text2,
          onTap: _busy ? null : () => _reschedule(order),
        ));
      }
      btns.add(_ActionBtn(
        label: 'Написать менеджеру',
        icon: Icons.chat_bubble_outline,
        color: c.primary,
        onTap: () => _snack('TODO: открыть чат с менеджером'),
        outlined: true,
      ));
    }

    if (ackBanner == null && btns.isEmpty) {
      return const SizedBox.shrink();
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (ackBanner != null) ackBanner,
        if (btns.isNotEmpty)
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: btns,
          ),
      ],
    );
  }

  // ── Status timeline ───────────────────────────────────────────────────────

  Widget _buildTimeline(
    BuildContext context,
    OrderDetail order,
    AppColors c,
  ) {
    final logs = List<OrderStatusLog>.from(order.statusLogs)
      ..sort((a, b) {
        final ta = a.createdAt;
        final tb = b.createdAt;
        if (ta == null && tb == null) return 0;
        if (ta == null) return 1;
        if (tb == null) return -1;
        return tb.compareTo(ta); // newest first
      });

    return _Section(
      title: 'История статусов',
      colors: c,
      child: logs.isEmpty
          ? Text(
              'Нет записей',
              style: TextStyle(fontSize: 12, color: c.text3),
            )
          : Column(
              children: logs
                  .map((l) => _TimelineItem(log: l, colors: c))
                  .toList(),
            ),
    );
  }

  // ── Documents (staff only) ────────────────────────────────────────────────

  Widget _buildDocuments(
    BuildContext context,
    OrderDetail order,
    AppColors c,
  ) {
    return _Section(
      title: 'Документы',
      colors: c,
      child: FutureBuilder<List<OrderDocument>>(
        future: _docsFuture,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const Padding(
              padding: EdgeInsets.all(8),
              child: Center(child: CircularProgressIndicator()),
            );
          }
          if (snap.hasError) {
            return Text(
              apiErrorMessage(snap.error!),
              style: TextStyle(fontSize: 12, color: c.red),
            );
          }
          final docs = snap.data ?? const [];
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Generate invoice bar — единый счёт как на вебе (059de77):
              // вместо предварительного/финального одна кнопка doc_type=invoice.
              Row(
                children: [
                  _SmallBtn(
                    label: 'Выставить счёт',
                    onTap: _busy
                        ? null
                        : () => _generateInvoice(order.id, 'invoice'),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              if (docs.isEmpty)
                Text(
                  'Документов ещё нет',
                  style: TextStyle(fontSize: 12, color: c.text3),
                )
              else
                ...docs.map(
                  (d) => _DocumentRow(
                    doc: d,
                    colors: c,
                    onDownload: () => _snack(
                      'TODO: скачать PDF — '
                      'GET /orders/${order.id}'
                      '/documents/${d.id}/download',
                    ),
                    onSendToChat: d.status == 'ready'
                        ? () => _sendDocToChat(order.id, d.id)
                        : null,
                  ),
                ),
            ],
          );
        },
      ),
    );
  }

  Future<void> _generateInvoice(
    String orderId,
    String docType,
  ) =>
      _run(() async {
        await OrdersRepository.instance
            .generateInvoice(orderId, docType);
        _snack('Счёт выставлен');
        setState(() {
          _docsFuture =
              OrdersRepository.instance.listDocuments(orderId);
        });
      });

  Future<void> _sendDocToChat(String orderId, String docId) =>
      _run(() async {
        await OrdersRepository.instance.sendDocToChat(orderId, docId);
        _snack('Документ отправлен в чат');
        setState(() {
          _docsFuture =
              OrdersRepository.instance.listDocuments(orderId);
        });
      });
}

// ---------------------------------------------------------------------------
// Small helpers / formatters
// ---------------------------------------------------------------------------

String _fmtDate(DateTime dt) =>
    '${dt.day.toString().padLeft(2, '0')}.${dt.month.toString().padLeft(2, '0')}.${dt.year}';

String _fmtNum(double v) {
  if (v == v.truncateToDouble()) {
    return v.toStringAsFixed(0).replaceAllMapped(
          RegExp(r'(\d)(?=(\d{3})+$)'),
          (m) => '${m[1]} ',
        );
  }
  return v.toString();
}

String _fmtMoney(double v) =>
    v.toStringAsFixed(2).replaceAllMapped(
      RegExp(r'(\d)(?=(\d{3})+(?=\.))'),
      (m) => '${m[1]} ',
    );

// ---------------------------------------------------------------------------
// Private reusable widgets
// ---------------------------------------------------------------------------

class _Card extends StatelessWidget {
  const _Card({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: c.bg2,
        border: Border.all(color: c.border),
        borderRadius: BorderRadius.circular(8),
      ),
      child: child,
    );
  }
}

class _Section extends StatelessWidget {
  const _Section({
    required this.title,
    required this.colors,
    required this.child,
  });

  final String title;
  final AppColors colors;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w700,
              color: colors.text2,
              letterSpacing: 0.3,
            ),
          ),
          const SizedBox(height: 10),
          child,
        ],
      ),
    );
  }
}

// Detail grid row model
class _DetailRow {
  const _DetailRow({required this.label, this.text, this.child})
      : assert(
          text != null || child != null,
          'Provide text or child',
        );

  final String label;
  final String? text;
  final Widget? child;
}

class _DetailsGridRow extends StatelessWidget {
  const _DetailsGridRow({required this.row, required this.colors});

  final _DetailRow row;
  final AppColors colors;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 150,
            child: Text(
              row.label,
              style: TextStyle(fontSize: 12, color: colors.text3),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: row.child ??
                Text(
                  row.text!,
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w500,
                    color: colors.text,
                  ),
                ),
          ),
        ],
      ),
    );
  }
}

class _StatusBadge extends StatelessWidget {
  const _StatusBadge({required this.label, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontSize: 12,
          fontWeight: FontWeight.w600,
          color: color,
        ),
      ),
    );
  }
}

class _UuidCell extends StatelessWidget {
  const _UuidCell({required this.value, required this.onSnack});

  final String value;
  final void Function(String) onSnack;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return GestureDetector(
      onTap: () {
        Clipboard.setData(ClipboardData(text: value));
        onSnack('UUID скопирован');
      },
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Flexible(
            child: Text(
              '${value.substring(0, 8)}…',
              style: TextStyle(
                fontSize: 12,
                fontFamily: 'monospace',
                color: c.text2,
              ),
            ),
          ),
          const SizedBox(width: 4),
          Icon(Icons.copy_rounded, size: 13, color: c.text3),
        ],
      ),
    );
  }
}

class _ContactCell extends StatelessWidget {
  const _ContactCell({
    required this.accentColor,
    required this.onSnack,
    this.name,
    this.phone,
  });

  final String? name;
  final String? phone;
  final Color accentColor;
  final void Function(String) onSnack;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        if (name != null && name!.isNotEmpty)
          Text(name!, style: const TextStyle(fontSize: 13)),
        if (phone != null && phone!.isNotEmpty)
          CopyablePhone(
            phone,
            style: TextStyle(
              fontSize: 13,
              color: accentColor,
            ),
          ),
      ],
    );
  }
}

class _MoneyChip extends StatelessWidget {
  const _MoneyChip({
    required this.label,
    required this.value,
    required this.colors,
    this.valueColor,
  });

  final String label;
  final String value;
  final Color? valueColor;
  final AppColors colors;

  @override
  Widget build(BuildContext context) {
    return RichText(
      text: TextSpan(
        children: [
          TextSpan(
            text: '$label: ',
            style: TextStyle(fontSize: 12, color: colors.text3),
          ),
          TextSpan(
            text: value,
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w700,
              color: valueColor ?? colors.text,
            ),
          ),
        ],
      ),
    );
  }
}

class _ActionBtn extends StatelessWidget {
  const _ActionBtn({
    required this.label,
    required this.icon,
    required this.color,
    required this.onTap,
    this.outlined = false,
  });

  final String label;
  final IconData icon;
  final Color color;
  final VoidCallback? onTap;
  final bool outlined;

  @override
  Widget build(BuildContext context) {
    if (outlined) {
      return OutlinedButton.icon(
        onPressed: onTap,
        icon: Icon(icon, size: 16),
        label: Text(label),
        style: OutlinedButton.styleFrom(
          foregroundColor: color,
          side: BorderSide(color: color),
          padding:
              const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
          textStyle: const TextStyle(
              fontSize: 13, fontWeight: FontWeight.w600),
          shape: const StadiumBorder(),
        ),
      );
    }
    return FilledButton.icon(
      onPressed: onTap,
      icon: Icon(icon, size: 16),
      label: Text(label),
      style: FilledButton.styleFrom(
        backgroundColor: color,
        foregroundColor: Colors.white,
        padding:
            const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        textStyle:
            const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
        shape: const StadiumBorder(),
      ),
    );
  }
}

class _SmallBtn extends StatelessWidget {
  const _SmallBtn({required this.label, required this.onTap});

  final String label;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton(
      onPressed: onTap,
      style: OutlinedButton.styleFrom(
        padding:
            const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        textStyle:
            const TextStyle(fontSize: 11, fontWeight: FontWeight.w500),
        minimumSize: Size.zero,
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(6),
        ),
      ),
      child: Text(label),
    );
  }
}

class _TimelineItem extends StatelessWidget {
  const _TimelineItem({required this.log, required this.colors});

  final OrderStatusLog log;
  final AppColors colors;

  @override
  Widget build(BuildContext context) {
    final fromLabel =
        kStatusLabels[log.fromStatus] ?? log.fromStatus ?? '';
    final toLabel = kStatusLabels[log.toStatus] ?? log.toStatus;
    final toColor = colors.statusColor(log.toStatus);
    final roleLabel = _kRoleLabels[log.changedByRole] ??
        log.changedByRole ??
        '';

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 68,
            child: Text(
              log.createdAt != null
                  ? '${_fmtDate(log.createdAt!)}\n'
                    '${log.createdAt!.hour.toString().padLeft(2, '0')}:'
                    '${log.createdAt!.minute.toString().padLeft(2, '0')}'
                  : '',
              style: TextStyle(
                fontSize: 10,
                color: colors.text3,
                height: 1.4,
              ),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Wrap(
                  spacing: 4,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    if (fromLabel.isNotEmpty) ...[
                      Text(
                        fromLabel,
                        style: TextStyle(
                          fontSize: 11,
                          color: colors.text3,
                        ),
                      ),
                      const Text('→',
                          style: TextStyle(fontSize: 11)),
                    ],
                    _StatusBadge(label: toLabel, color: toColor),
                  ],
                ),
                if (log.comment?.isNotEmpty == true) ...[
                  const SizedBox(height: 2),
                  Text(
                    log.comment!,
                    style: TextStyle(
                      fontSize: 11,
                      color: colors.text2,
                    ),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(width: 8),
          Text(
            roleLabel,
            style: TextStyle(
              fontSize: 10,
              color: colors.roleColor(log.changedByRole ?? ''),
            ),
          ),
        ],
      ),
    );
  }
}

class _DocumentRow extends StatelessWidget {
  const _DocumentRow({
    required this.doc,
    required this.colors,
    required this.onDownload,
    this.onSendToChat,
  });

  final OrderDocument doc;
  final AppColors colors;
  final VoidCallback onDownload;
  final VoidCallback? onSendToChat;

  @override
  Widget build(BuildContext context) {
    final typeLabel =
        _kDocTypeLabels[doc.docType] ?? doc.docType;
    final statusLabel =
        _kDocStatusLabels[doc.status] ?? doc.status;
    final statusColor = switch (doc.status) {
      'ready' => colors.green,
      'sent' => colors.primary,
      'cancelled' => colors.red,
      _ => colors.text3,
    };
    final canDownload =
        doc.status == 'ready' || doc.status == 'sent';

    return Container(
      padding: const EdgeInsets.symmetric(vertical: 8),
      decoration: BoxDecoration(
        border: Border(
          bottom: BorderSide(color: colors.border),
        ),
      ),
      child: Row(
        children: [
          Icon(Icons.description_outlined,
              size: 20, color: colors.text3),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '$typeLabel  ${doc.docNumber}',
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                Text(
                  statusLabel,
                  style: TextStyle(fontSize: 11, color: statusColor),
                ),
              ],
            ),
          ),
          if (canDownload) ...[
            _SmallBtn(label: 'PDF', onTap: onDownload),
            const SizedBox(width: 6),
          ],
          if (onSendToChat != null)
            _SmallBtn(label: 'В чат', onTap: onSendToChat),
        ],
      ),
    );
  }
}
