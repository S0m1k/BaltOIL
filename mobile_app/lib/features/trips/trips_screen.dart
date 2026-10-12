import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/theme.dart';
import '../auth/auth_repository.dart';
import '../orders/order_models.dart';
import '../orders/orders_repository.dart';
import 'trips_repository.dart';

// ---------------------------------------------------------------------------
// Status-filter definition (mirrors web pane-trips filter options).
// ---------------------------------------------------------------------------

// Порядок и дефолт — как на вебе (081b2e3): «Рейсы» открываются журналом
// завершённых, активные — вторым фильтром.
const _kFilters = <({TripStatus? status, String label})>[
  (status: TripStatus.completed, label: 'Завершённые'),
  (status: TripStatus.inTransit, label: 'Активные (в пути)'),
  (status: null, label: 'Все рейсы'),
  (status: TripStatus.cancelled, label: 'Отменённые'),
];

// ---------------------------------------------------------------------------
// Screen
// ---------------------------------------------------------------------------

class TripsScreen extends StatefulWidget {
  const TripsScreen({super.key, required this.user});

  final CurrentUser user;

  @override
  State<TripsScreen> createState() => _TripsScreenState();
}

class _TripsScreenState extends State<TripsScreen> {
  int _filterIndex = 0; // default: completed (журнал закрытых рейсов, как на вебе)
  late Future<List<Trip>> _future;

  @override
  void initState() {
    super.initState();
    _load();
    // Warm up fuel-type label cache (best-effort).
    OrdersRepository.instance
        .fuelTypes()
        .catchError((_) => <FuelType>[]);
  }

  void _load() {
    final filter = _kFilters[_filterIndex];
    // Drivers see only their own trips; managers/admins see all.
    final driverId =
        widget.user.role == 'driver' ? widget.user.id : null;
    setState(() {
      _future = TripsRepository.instance.list(
        status: filter.status,
        driverId: driverId,
      );
    });
  }

  Future<void> _refresh() async {
    final filter = _kFilters[_filterIndex];
    final driverId =
        widget.user.role == 'driver' ? widget.user.id : null;
    final future = TripsRepository.instance.list(
      status: filter.status,
      driverId: driverId,
    );
    setState(() {
      _future = future;
    });
    await future;
  }

  void _setFilter(int index) {
    if (_filterIndex == index) return;
    _filterIndex = index;
    _load();
  }

  // ---------------------------------------------------------------------------
  // Driver action: complete trip
  // ---------------------------------------------------------------------------

  Future<void> _promptComplete(Trip trip) async {
    final volController = TextEditingController(
      text: trip.volumePlanned.toStringAsFixed(0),
    );
    final notesController = TextEditingController();

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: ctx.colors.bg2,
        title: Text(
          'Подтвердить доставку',
          style: TextStyle(color: ctx.colors.text),
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Укажите фактически доставленный объём. '
              'Данные будут переданы в заявку и скорректируют остаток на складе.',
              style: TextStyle(
                  color: ctx.colors.text2, fontSize: 13),
            ),
            const SizedBox(height: 16),
            Text('Фактический объём (л)',
                style: TextStyle(
                    color: ctx.colors.text2, fontSize: 13)),
            const SizedBox(height: 6),
            TextField(
              controller: volController,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              autofocus: true,
              decoration: InputDecoration(
                hintText: 'Объём',
                hintStyle: TextStyle(color: ctx.colors.text3),
              ),
            ),
            const SizedBox(height: 12),
            Text('Примечания',
                style: TextStyle(
                    color: ctx.colors.text2, fontSize: 13)),
            const SizedBox(height: 6),
            TextField(
              controller: notesController,
              decoration: InputDecoration(
                hintText: '...',
                hintStyle: TextStyle(color: ctx.colors.text3),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: Text('Отмена',
                style: TextStyle(color: ctx.colors.text3)),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Подтвердить'),
          ),
        ],
      ),
    );

    if (confirmed != true || !mounted) return;

    final vol = double.tryParse(volController.text.trim());
    if (vol == null || vol <= 0) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
              content: Text('Укажите фактический объём')),
        );
      }
      return;
    }

    try {
      await TripsRepository.instance.complete(
        trip.id,
        volumeActual: vol,
        driverNotes: notesController.text.trim().isEmpty
            ? null
            : notesController.text.trim(),
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
              content: Text(
                  'Доставка подтверждена! Заявка переведена в «Доставлено».')),
        );
        _refresh();
      }
    } on Object catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(apiErrorMessage(e))),
        );
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Manager/admin action: cancel trip
  // ---------------------------------------------------------------------------

  Future<void> _promptCancel(Trip trip) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: ctx.colors.bg2,
        title: Text('Отменить рейс?',
            style: TextStyle(color: ctx.colors.text)),
        content: Text(
          'Рейс будет отменён, списанное топливо вернётся на склад. '
          'Статус заявки останется «В рейсе» — скорректируйте его вручную.',
          style:
              TextStyle(color: ctx.colors.text2, fontSize: 13),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: Text('Отмена',
                style: TextStyle(color: ctx.colors.text3)),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: ctx.colors.red,
            ),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Отменить рейс'),
          ),
        ],
      ),
    );

    if (confirmed != true || !mounted) return;

    try {
      await TripsRepository.instance.cancel(trip.id);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
              content: Text(
                  'Рейс отменён, топливо возвращено на склад')),
        );
        _refresh();
      }
    } on Object catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(apiErrorMessage(e))),
        );
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Build
  // ---------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // Filter chips
        Container(
          color: c.bg,
          padding:
              const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: List.generate(_kFilters.length, (i) {
                final selected = i == _filterIndex;
                return Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: FilterChip(
                    label: Text(_kFilters[i].label),
                    selected: selected,
                    onSelected: (_) => _setFilter(i),
                    selectedColor: c.primaryDim,
                    checkmarkColor: c.primary,
                    labelStyle: TextStyle(
                      color: selected ? c.primary : c.text2,
                      fontWeight: selected
                          ? FontWeight.w600
                          : FontWeight.normal,
                      fontSize: 13,
                    ),
                    side: BorderSide(
                      color: selected ? c.primary : c.border,
                    ),
                    backgroundColor: c.bg2,
                    showCheckmark: false,
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(20)),
                    padding: const EdgeInsets.symmetric(
                        horizontal: 12, vertical: 4),
                  ),
                );
              }),
            ),
          ),
        ),
        const Divider(height: 1),
        // Trip list
        Expanded(
          child: RefreshIndicator(
            onRefresh: _refresh,
            child: FutureBuilder<List<Trip>>(
              future: _future,
              builder: (ctx, snap) {
                if (snap.connectionState != ConnectionState.done) {
                  return const Center(
                      child: CircularProgressIndicator());
                }
                if (snap.hasError) {
                  return _ErrorRetry(
                    message: apiErrorMessage(snap.error!),
                    onRetry: _refresh,
                  );
                }
                final trips = snap.data ?? const [];
                if (trips.isEmpty) {
                  return ListView(children: [
                    const SizedBox(height: 120),
                    Center(
                      child: Column(
                        children: [
                          Icon(Icons.local_shipping_outlined,
                              size: 48, color: c.text3),
                          const SizedBox(height: 12),
                          Text(
                            _kFilters[_filterIndex].status ==
                                    TripStatus.inTransit
                                ? 'Нет активных рейсов.\nНачните рейс со страницы «Заявки».'
                                : 'Рейсов нет',
                            style: TextStyle(color: c.text3),
                            textAlign: TextAlign.center,
                          ),
                        ],
                      ),
                    ),
                  ]);
                }
                return ListView.separated(
                  padding: const EdgeInsets.all(12),
                  itemCount: trips.length,
                  separatorBuilder: (_, __) =>
                      const SizedBox(height: 8),
                  itemBuilder: (ctx, i) => _TripCard(
                    trip: trips[i],
                    user: widget.user,
                    onComplete: () => _promptComplete(trips[i]),
                    onCancel: () => _promptCancel(trips[i]),
                  ),
                );
              },
            ),
          ),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Trip card widget (mirrors .trip-card CSS with left-border accent)
// ---------------------------------------------------------------------------

class _TripCard extends StatelessWidget {
  const _TripCard({
    required this.trip,
    required this.user,
    required this.onComplete,
    required this.onCancel,
  });

  final Trip trip;
  final CurrentUser user;
  final VoidCallback onComplete;
  final VoidCallback onCancel;

  Color _statusBorderColor(AppColors c) => switch (trip.status) {
        TripStatus.planned => c.statusNew,
        TripStatus.inTransit => c.primary,
        TripStatus.completed => c.green,
        TripStatus.cancelled => c.statusClosed,
      };

  Color _statusTextColor(AppColors c) => switch (trip.status) {
        TripStatus.planned => c.statusNew,
        TripStatus.inTransit => c.primary,
        TripStatus.completed => c.green,
        TripStatus.cancelled => c.statusClosed,
      };

  String get _statusLabel =>
      kTripStatusLabels[trip.status] ?? trip.status.toApiString();

  String _fmtDate(DateTime dt) {
    final local = dt.toLocal();
    final d = local.day.toString().padLeft(2, '0');
    final mo = local.month.toString().padLeft(2, '0');
    final y = (local.year % 100).toString().padLeft(2, '0');
    final h = local.hour.toString().padLeft(2, '0');
    final mi = local.minute.toString().padLeft(2, '0');
    return '$d.$mo.$y $h:$mi';
  }

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final borderColor = _statusBorderColor(c);
    final isManagerOrAdmin =
        user.role == 'manager' || user.role == 'admin';
    final isDriver = user.role == 'driver';

    final fuelLabel = trip.invFuelType != null
        ? FuelCatalog.label(trip.invFuelType!)
        : null;

    final volActual = trip.volumeActual;
    final volStr = volActual != null
        ? 'факт ${volActual.toStringAsFixed(0)} л / план ${trip.volumePlanned.toStringAsFixed(0)} л'
        : 'план ${trip.volumePlanned.toStringAsFixed(0)} л';

    final showComplete = trip.status == TripStatus.inTransit &&
        (isDriver || isManagerOrAdmin);
    final showCancel = trip.status == TripStatus.inTransit &&
        isManagerOrAdmin;

    return Container(
      decoration: BoxDecoration(
        color: c.bg2,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: c.border),
      ),
      clipBehavior: Clip.hardEdge,
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Left status border — mirrors .trip-card border-left CSS
            Container(width: 4, color: borderColor),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Header row: status badge + order ref + fuel badge
                    Row(
                      children: [
                        _StatusBadge(
                          label: _statusLabel,
                          color: _statusTextColor(c),
                        ),
                        const SizedBox(width: 8),
                        if (trip.invOrderNumber != null) ...[
                          Text(
                            trip.invOrderNumber!,
                            style: TextStyle(
                              color: c.text,
                              fontWeight: FontWeight.w700,
                              fontSize: 13,
                              fontFamily: 'monospace',
                            ),
                          ),
                          const SizedBox(width: 8),
                        ],
                        if (fuelLabel != null)
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 6, vertical: 2),
                            decoration: BoxDecoration(
                              color: c.primaryDim,
                              borderRadius: BorderRadius.circular(4),
                            ),
                            child: Text(
                              fuelLabel,
                              style: TextStyle(
                                color: c.primary,
                                fontSize: 11,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    // Volume
                    Text(volStr,
                        style: TextStyle(
                            color: c.text2, fontSize: 13)),
                    // Address
                    if (trip.deliveryAddress != null &&
                        trip.deliveryAddress!.isNotEmpty) ...[
                      const SizedBox(height: 4),
                      Row(
                        children: [
                          Icon(Icons.arrow_forward,
                              size: 12, color: c.text3),
                          const SizedBox(width: 4),
                          Expanded(
                            child: Text(
                              trip.deliveryAddress!,
                              style: TextStyle(
                                  color: c.text3, fontSize: 12),
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                        ],
                      ),
                    ],
                    // Meta rows (manager/admin only: driver, client)
                    if ((isManagerOrAdmin &&
                            trip.invDriverName != null) ||
                        (isManagerOrAdmin &&
                            trip.invClientName != null) ||
                        trip.departedAt != null ||
                        trip.arrivedAt != null) ...[
                      const SizedBox(height: 6),
                      if (isManagerOrAdmin &&
                          trip.invDriverName != null)
                        _MetaRow(
                            label: 'Водитель',
                            value: trip.invDriverName!),
                      if (isManagerOrAdmin &&
                          trip.invClientName != null)
                        _MetaRow(
                            label: 'Клиент',
                            value: trip.invClientName!),
                      if (trip.departedAt != null)
                        _MetaRow(
                            label: 'Выехал',
                            value: _fmtDate(trip.departedAt!)),
                      if (trip.arrivedAt != null)
                        _MetaRow(
                            label: 'Прибыл',
                            value: _fmtDate(trip.arrivedAt!)),
                    ],
                    // Action buttons
                    if (showComplete || showCancel) ...[
                      const SizedBox(height: 14),
                      Wrap(
                        spacing: 8,
                        runSpacing: 6,
                        children: [
                          if (showComplete)
                            FilledButton.icon(
                              onPressed: onComplete,
                              style: FilledButton.styleFrom(
                                backgroundColor: c.green,
                                foregroundColor: Colors.white,
                                padding: const EdgeInsets.symmetric(
                                    horizontal: 14, vertical: 8),
                                textStyle: const TextStyle(
                                    fontSize: 13,
                                    fontWeight: FontWeight.w600),
                              ),
                              icon: const Icon(Icons.check, size: 16),
                              label:
                                  const Text('Подтвердить доставку'),
                            ),
                          if (showCancel)
                            OutlinedButton(
                              onPressed: onCancel,
                              style: OutlinedButton.styleFrom(
                                foregroundColor: c.red,
                                side: BorderSide(color: c.red),
                                padding: const EdgeInsets.symmetric(
                                    horizontal: 14, vertical: 8),
                                textStyle: const TextStyle(
                                    fontSize: 13,
                                    fontWeight: FontWeight.w600),
                              ),
                              child: const Text('Отменить рейс'),
                            ),
                        ],
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Helper widgets
// ---------------------------------------------------------------------------

class _StatusBadge extends StatelessWidget {
  const _StatusBadge({required this.label, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding:
          const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontSize: 11,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

class _MetaRow extends StatelessWidget {
  const _MetaRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Padding(
      padding: const EdgeInsets.only(bottom: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 72,
            child: Text(
              label,
              style: TextStyle(
                  color: c.text3.withValues(alpha: 0.7),
                  fontSize: 11),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              value,
              style:
                  TextStyle(color: c.text3, fontSize: 11),
            ),
          ),
        ],
      ),
    );
  }
}

class _ErrorRetry extends StatelessWidget {
  const _ErrorRetry(
      {required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return ListView(children: [
      const SizedBox(height: 120),
      Center(
          child:
              Text(message, textAlign: TextAlign.center)),
      const SizedBox(height: 12),
      Center(
        child: OutlinedButton(
            onPressed: onRetry,
            child: const Text('Повторить')),
      ),
    ]);
  }
}
