import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/theme.dart';
import '../auth/auth_repository.dart';
import '../orders/order_models.dart';
import 'report_repository.dart';

// ---------------------------------------------------------------------------
// Public entry-point widget — keep signature identical to the stub.
// No Scaffold/AppBar — the shell (home_screen) provides those.
// ---------------------------------------------------------------------------

class ReportScreen extends StatefulWidget {
  const ReportScreen({super.key, required this.user});

  final CurrentUser user;

  @override
  State<ReportScreen> createState() => _ReportScreenState();
}

class _ReportScreenState extends State<ReportScreen> {
  // ---- driver selector state ----
  List<UserBrief> _drivers = [];
  bool _driversLoading = false;
  UserBrief? _selectedDriver;

  // ---- date range ----
  late DateTime _dateFrom;
  late DateTime _dateTo;

  // ---- report future ----
  Future<DriverReport>? _reportFuture;

  // ---- xlsx request ----
  bool _xlsxRequesting = false;

  bool get _isDriver => widget.user.role == 'driver';

  @override
  void initState() {
    super.initState();
    final now = DateTime.now();
    _dateFrom = DateTime(now.year, now.month, 1);
    _dateTo = DateTime(now.year, now.month + 1, 0, 23, 59, 59);

    if (_isDriver) {
      // Driver sees only their own report — use self and fetch immediately.
      _selectedDriver = UserBrief(
        id: widget.user.id,
        fullName: widget.user.fullName,
      );
      _fetch();
    } else {
      _loadDrivers();
    }
  }

  Future<void> _loadDrivers() async {
    setState(() => _driversLoading = true);
    try {
      final list = await AuthRepository.instance.listByRole('driver');
      if (!mounted) return;
      setState(() {
        _drivers = list;
        _driversLoading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _driversLoading = false);
    }
  }

  void _fetch() {
    final driver = _selectedDriver;
    if (driver == null) return;
    setState(() {
      _reportFuture = ReportRepository.instance.driverReport(
        driverId: driver.id,
        dateFrom: _dateFrom,
        dateTo: _dateTo,
      );
    });
  }

  Future<void> _pickDateRange() async {
    final range = await showDateRangePicker(
      context: context,
      firstDate: DateTime(2023),
      lastDate: DateTime.now().add(const Duration(days: 1)),
      initialDateRange: DateTimeRange(start: _dateFrom, end: _dateTo),
    );
    if (range == null || !mounted) return;
    setState(() {
      _dateFrom = range.start;
      _dateTo = DateTime(
        range.end.year,
        range.end.month,
        range.end.day,
        23,
        59,
        59,
      );
    });
    _fetch();
  }

  Future<void> _requestXlsx() async {
    final driver = _selectedDriver;
    if (driver == null || _xlsxRequesting) return;
    setState(() => _xlsxRequesting = true);
    try {
      await ReportRepository.instance.requestDriverReportXlsx(
        driverId: driver.id,
        dateFrom: _dateFrom,
        dateTo: _dateTo,
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Отчёт формируется — вы получите уведомление со ссылкой'),
        ),
      );
    } on Exception catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(apiErrorMessage(e))),
      );
    } finally {
      if (mounted) setState(() => _xlsxRequesting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return RefreshIndicator(
      onRefresh: () async => _fetch(),
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          SliverToBoxAdapter(
            child: _FilterBar(
              isDriver: _isDriver,
              drivers: _drivers,
              driversLoading: _driversLoading,
              selectedDriver: _selectedDriver,
              dateFrom: _dateFrom,
              dateTo: _dateTo,
              onDriverChanged: (d) {
                _selectedDriver = d;
                _fetch();
              },
              onPickDates: _pickDateRange,
            ),
          ),
          if (_reportFuture != null)
            SliverFillRemaining(
              hasScrollBody: false,
              child: FutureBuilder<DriverReport>(
                future: _reportFuture,
                builder: (context, snap) {
                  if (snap.connectionState != ConnectionState.done) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  if (snap.hasError) {
                    return _ErrorView(message: apiErrorMessage(snap.error!));
                  }
                  final report = snap.data!;
                  return _ReportBody(
                    report: report,
                    colors: colors,
                    xlsxRequesting: _xlsxRequesting,
                    onRequestXlsx: _requestXlsx,
                  );
                },
              ),
            )
          else
            SliverFillRemaining(
              hasScrollBody: false,
              child: _EmptyHint(
                colors: colors,
                hasDriver: _isDriver,
              ),
            ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Filter bar: driver selector + date-range chip
// ---------------------------------------------------------------------------

class _FilterBar extends StatelessWidget {
  const _FilterBar({
    required this.isDriver,
    required this.drivers,
    required this.driversLoading,
    required this.selectedDriver,
    required this.dateFrom,
    required this.dateTo,
    required this.onDriverChanged,
    required this.onPickDates,
  });

  final bool isDriver;
  final List<UserBrief> drivers;
  final bool driversLoading;
  final UserBrief? selectedDriver;
  final DateTime dateFrom;
  final DateTime dateTo;
  final ValueChanged<UserBrief?> onDriverChanged;
  final VoidCallback onPickDates;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      color: colors.bg2,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Отчёт по рейсам',
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w700,
              color: colors.text,
            ),
          ),
          const SizedBox(height: 12),
          if (!isDriver) ...[
            _DriverDropdown(
              drivers: drivers,
              loading: driversLoading,
              selected: selectedDriver,
              onChanged: onDriverChanged,
              colors: colors,
            ),
            const SizedBox(height: 10),
          ],
          _DateRangeChip(
            dateFrom: dateFrom,
            dateTo: dateTo,
            onTap: onPickDates,
            colors: colors,
          ),
        ],
      ),
    );
  }
}

class _DriverDropdown extends StatelessWidget {
  const _DriverDropdown({
    required this.drivers,
    required this.loading,
    required this.selected,
    required this.onChanged,
    required this.colors,
  });

  final List<UserBrief> drivers;
  final bool loading;
  final UserBrief? selected;
  final ValueChanged<UserBrief?> onChanged;
  final AppColors colors;

  @override
  Widget build(BuildContext context) {
    if (loading) {
      return Row(
        children: [
          SizedBox(
            width: 16,
            height: 16,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              color: colors.primary,
            ),
          ),
          const SizedBox(width: 8),
          Text('Загрузка водителей…', style: TextStyle(color: colors.text3)),
        ],
      );
    }
    return DropdownButtonFormField<UserBrief>(
      value: selected,
      hint: Text('Выберите водителя', style: TextStyle(color: colors.text3)),
      isExpanded: true,
      decoration: InputDecoration(
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: BorderSide(color: colors.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: BorderSide(color: colors.border),
        ),
        filled: true,
        fillColor: colors.bg3,
      ),
      dropdownColor: colors.bg2,
      style: TextStyle(color: colors.text, fontSize: 14),
      items: drivers
          .map(
            (d) => DropdownMenuItem<UserBrief>(
              value: d,
              child: Text(d.label, overflow: TextOverflow.ellipsis),
            ),
          )
          .toList(),
      onChanged: onChanged,
    );
  }
}

class _DateRangeChip extends StatelessWidget {
  const _DateRangeChip({
    required this.dateFrom,
    required this.dateTo,
    required this.onTap,
    required this.colors,
  });

  final DateTime dateFrom;
  final DateTime dateTo;
  final VoidCallback onTap;
  final AppColors colors;

  String _fmt(DateTime d) =>
      '${d.day.toString().padLeft(2, '0')}.${d.month.toString().padLeft(2, '0')}.${d.year}';

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
        decoration: BoxDecoration(
          color: colors.bg3,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: colors.border),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.calendar_month_outlined, size: 18, color: colors.primary),
            const SizedBox(width: 8),
            Text(
              '${_fmt(dateFrom)} — ${_fmt(dateTo)}',
              style: TextStyle(color: colors.text, fontSize: 14),
            ),
            const SizedBox(width: 6),
            Icon(Icons.arrow_drop_down, size: 20, color: colors.text3),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Report body: summary cards + trips list + XLSX button
// ---------------------------------------------------------------------------

class _ReportBody extends StatelessWidget {
  const _ReportBody({
    required this.report,
    required this.colors,
    required this.xlsxRequesting,
    required this.onRequestXlsx,
  });

  final DriverReport report;
  final AppColors colors;
  final bool xlsxRequesting;
  final VoidCallback onRequestXlsx;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _SummaryGrid(report: report, colors: colors),
          const SizedBox(height: 16),
          _XlsxButton(
            requesting: xlsxRequesting,
            onTap: onRequestXlsx,
            colors: colors,
          ),
          const SizedBox(height: 16),
          if (report.trips.isEmpty)
            Center(
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 32),
                child: Text(
                  'Нет рейсов за выбранный период',
                  style: TextStyle(color: colors.text3, fontSize: 14),
                ),
              ),
            )
          else ...[
            Text(
              'Рейсы (${report.trips.length})',
              style: TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.w600,
                color: colors.text,
              ),
            ),
            const SizedBox(height: 8),
            ...report.trips.map(
              (trip) => _TripCard(trip: trip, colors: colors),
            ),
          ],
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Summary grid — 3 stat tiles
// ---------------------------------------------------------------------------

class _SummaryGrid extends StatelessWidget {
  const _SummaryGrid({required this.report, required this.colors});

  final DriverReport report;
  final AppColors colors;

  String _vol(double v) => '${v.toStringAsFixed(0)} л';

  @override
  Widget build(BuildContext context) {
    final inProgress = report.totalTrips - report.completedTrips - report.cancelledTrips;
    return Column(
      children: [
        Row(
          children: [
            Expanded(
              child: _StatTile(
                label: 'Рейсов всего',
                value: report.totalTrips.toString(),
                color: colors.primary,
                colors: colors,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: _StatTile(
                label: 'Завершено',
                value: report.completedTrips.toString(),
                color: colors.accent,
                colors: colors,
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            Expanded(
              child: _StatTile(
                label: 'Отменено',
                value: report.cancelledTrips.toString(),
                color: colors.red,
                colors: colors,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: _StatTile(
                label: 'В процессе',
                value: inProgress.clamp(0, report.totalTrips).toString(),
                color: colors.statusProgress,
                colors: colors,
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            Expanded(
              child: _StatTile(
                label: 'Объём план',
                value: _vol(report.totalVolumePlanned),
                color: colors.text2,
                colors: colors,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: _StatTile(
                label: 'Объём факт',
                value: _vol(report.totalVolumeActual),
                color: colors.accent,
                colors: colors,
              ),
            ),
          ],
        ),
        if (report.totalDistanceKm != null) ...[
          const SizedBox(height: 10),
          _StatTile(
            label: 'Пробег',
            value: '${report.totalDistanceKm!.toStringAsFixed(0)} км',
            color: colors.text2,
            colors: colors,
          ),
        ],
      ],
    );
  }
}

class _StatTile extends StatelessWidget {
  const _StatTile({
    required this.label,
    required this.value,
    required this.color,
    required this.colors,
  });

  final String label;
  final String value;
  final Color color;
  final AppColors colors;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: colors.bg2,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: colors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: TextStyle(fontSize: 12, color: colors.text3),
          ),
          const SizedBox(height: 4),
          Text(
            value,
            style: TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w700,
              color: color,
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// XLSX download button
// ---------------------------------------------------------------------------

class _XlsxButton extends StatelessWidget {
  const _XlsxButton({
    required this.requesting,
    required this.onTap,
    required this.colors,
  });

  final bool requesting;
  final VoidCallback onTap;
  final AppColors colors;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton.icon(
      onPressed: requesting ? null : onTap,
      style: OutlinedButton.styleFrom(
        foregroundColor: colors.accent,
        side: BorderSide(color: colors.accent),
        padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
      icon: requesting
          ? SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                color: colors.accent,
              ),
            )
          : const Icon(Icons.download_outlined, size: 20),
      label: Text(
        requesting ? 'Запрашиваем…' : 'Скачать XLSX',
        style: const TextStyle(fontWeight: FontWeight.w600),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Individual trip card
// ---------------------------------------------------------------------------

class _TripCard extends StatelessWidget {
  const _TripCard({required this.trip, required this.colors});

  final TripItem trip;
  final AppColors colors;

  String _fmtDate(DateTime? dt) {
    if (dt == null) return '—';
    return '${dt.day.toString().padLeft(2, '0')}.${dt.month.toString().padLeft(2, '0')}'
        ' ${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
  }

  Color _statusColor(String status) => switch (status) {
        'completed' => colors.accent,
        'cancelled' => colors.red,
        'in_progress' => colors.statusProgress,
        _ => colors.text3,
      };

  String _statusLabel(String status) => switch (status) {
        'completed' => 'Завершён',
        'cancelled' => 'Отменён',
        'in_progress' => 'В пути',
        'pending' => 'Ожидает',
        _ => status,
      };

  @override
  Widget build(BuildContext context) {
    final fuelLabel = trip.invFuelType != null
        ? FuelCatalog.label(trip.invFuelType!)
        : null;
    final orderRef = trip.invOrderNumber ?? trip.orderId.substring(0, 8);

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: colors.bg2,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: colors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header row: order ref + status chip
          Row(
            children: [
              Expanded(
                child: Text(
                  'Заявка №$orderRef',
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: colors.text,
                  ),
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: _statusColor(trip.status).withOpacity(0.12),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  _statusLabel(trip.status),
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: _statusColor(trip.status),
                  ),
                ),
              ),
            ],
          ),
          if (trip.deliveryAddress != null && trip.deliveryAddress!.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              trip.deliveryAddress!,
              style: TextStyle(fontSize: 13, color: colors.text2),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ],
          const SizedBox(height: 8),
          // Volume row
          _InfoRow(
            label: 'Объём',
            value: fuelLabel != null
                ? '${trip.volumePlanned.toStringAsFixed(0)} л  $fuelLabel'
                    '${trip.volumeActual != null ? '  →  факт ${trip.volumeActual!.toStringAsFixed(0)} л' : ''}'
                : '${trip.volumePlanned.toStringAsFixed(0)} л'
                    '${trip.volumeActual != null ? '  →  ${trip.volumeActual!.toStringAsFixed(0)} л' : ''}',
            colors: colors,
          ),
          // Dates
          if (trip.departedAt != null)
            _InfoRow(
              label: 'Выезд',
              value: _fmtDate(trip.departedAt),
              colors: colors,
            ),
          if (trip.arrivedAt != null)
            _InfoRow(
              label: 'Прибытие',
              value: _fmtDate(trip.arrivedAt),
              colors: colors,
            ),
        ],
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({
    required this.label,
    required this.value,
    required this.colors,
  });

  final String label;
  final String value;
  final AppColors colors;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 3),
      child: Row(
        children: [
          Text(
            '$label: ',
            style: TextStyle(fontSize: 13, color: colors.text3),
          ),
          Expanded(
            child: Text(
              value,
              style: TextStyle(fontSize: 13, color: colors.text2),
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Error / empty states
// ---------------------------------------------------------------------------

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline, size: 48, color: colors.red),
            const SizedBox(height: 12),
            Text(
              message,
              textAlign: TextAlign.center,
              style: TextStyle(color: colors.text2, fontSize: 14),
            ),
          ],
        ),
      ),
    );
  }
}

class _EmptyHint extends StatelessWidget {
  const _EmptyHint({required this.colors, required this.hasDriver});

  final AppColors colors;
  final bool hasDriver;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(40),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.bar_chart_rounded, size: 56, color: colors.text3),
            const SizedBox(height: 14),
            Text(
              hasDriver
                  ? 'Выберите период и нажмите «Показать»'
                  : 'Выберите водителя и период для формирования отчёта',
              textAlign: TextAlign.center,
              style: TextStyle(color: colors.text3, fontSize: 14),
            ),
          ],
        ),
      ),
    );
  }
}
