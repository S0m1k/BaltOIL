import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/theme.dart';
import '../auth/auth_repository.dart';
import 'finance_repository.dart';

class FinanceScreen extends StatefulWidget {
  const FinanceScreen({super.key, required this.user});

  final CurrentUser user;

  @override
  State<FinanceScreen> createState() => _FinanceScreenState();
}

class _FinanceScreenState extends State<FinanceScreen> {
  // Date range — defaults to current month.
  late DateTime _dateFrom;
  late DateTime _dateTo;
  String? _statusFilter; // null = all

  late Future<_FinanceData> _future;

  @override
  void initState() {
    super.initState();
    final now = DateTime.now();
    _dateFrom = DateTime(now.year, now.month, 1);
    _dateTo = DateTime(now.year, now.month + 1, 0, 23, 59, 59);
    _reload();
  }

  void _reload() {
    setState(() {
      _future = _load();
    });
  }

  Future<_FinanceData> _load() async {
    final repo = FinanceRepository.instance;
    final results = await Future.wait([
      repo.report(dateFrom: _dateFrom, dateTo: _dateTo),
      repo.listPayments(
        dateFrom: _dateFrom,
        dateTo: _dateTo,
        status: _statusFilter,
      ),
    ]);
    return _FinanceData(
      report: results[0] as PaymentReport,
      payments: results[1] as List<Payment>,
    );
  }

  Future<void> _pickDateRange() async {
    final range = await showDateRangePicker(
      context: context,
      firstDate: DateTime(2023),
      lastDate: DateTime.now().add(const Duration(days: 1)),
      initialDateRange: DateTimeRange(start: _dateFrom, end: _dateTo),
    );
    if (range == null) return;
    _dateFrom = range.start;
    _dateTo = DateTime(
      range.end.year,
      range.end.month,
      range.end.day,
      23,
      59,
      59,
    );
    _reload();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return RefreshIndicator(
      onRefresh: () async => _reload(),
      child: FutureBuilder<_FinanceData>(
        future: _future,
        builder: (context, snap) {
          final loading = snap.connectionState != ConnectionState.done;
          final error =
              snap.hasError ? apiErrorMessage(snap.error!) : null;
          final data = snap.data;

          return CustomScrollView(
            physics: const AlwaysScrollableScrollPhysics(),
            slivers: [
              SliverToBoxAdapter(
                child: _FilterBar(
                  dateFrom: _dateFrom,
                  dateTo: _dateTo,
                  statusFilter: _statusFilter,
                  onPickDates: _pickDateRange,
                  onStatusChanged: (v) {
                    _statusFilter = v;
                    _reload();
                  },
                  colors: colors,
                ),
              ),
              if (loading)
                const SliverFillRemaining(
                  child: Center(child: CircularProgressIndicator()),
                )
              else if (error != null)
                SliverFillRemaining(
                  child: _ErrorRetry(
                    message: error,
                    onRetry: _reload,
                  ),
                )
              else if (data != null) ...[
                SliverToBoxAdapter(
                  child: _SummaryCards(
                    report: data.report,
                    colors: colors,
                  ),
                ),
                if (data.payments.isEmpty)
                  const SliverFillRemaining(
                    hasScrollBody: false,
                    child: Center(
                      child: Padding(
                        padding: EdgeInsets.all(32),
                        child: Text(
                          'Платежей за выбранный период нет',
                          textAlign: TextAlign.center,
                        ),
                      ),
                    ),
                  )
                else
                  SliverList(
                    delegate: SliverChildBuilderDelegate(
                      (ctx, i) => _PaymentCard(
                        payment: data.payments[i],
                        colors: colors,
                      ),
                      childCount: data.payments.length,
                    ),
                  ),
              ],
            ],
          );
        },
      ),
    );
  }
}

class _FinanceData {
  const _FinanceData({required this.report, required this.payments});
  final PaymentReport report;
  final List<Payment> payments;
}

// ---------------------------------------------------------------------------
// Filter bar
// ---------------------------------------------------------------------------

class _FilterBar extends StatelessWidget {
  const _FilterBar({
    required this.dateFrom,
    required this.dateTo,
    required this.statusFilter,
    required this.onPickDates,
    required this.onStatusChanged,
    required this.colors,
  });

  final DateTime dateFrom;
  final DateTime dateTo;
  final String? statusFilter;
  final VoidCallback onPickDates;
  final ValueChanged<String?> onStatusChanged;
  final AppColors colors;

  String _fmt(DateTime d) =>
      '${d.day.toString().padLeft(2, '0')}.${d.month.toString().padLeft(2, '0')}.${d.year}';

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Date range chip
          GestureDetector(
            onTap: onPickDates,
            child: Container(
              padding: const EdgeInsets.symmetric(
                  horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: colors.bg2,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: colors.border),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.date_range,
                      size: 16, color: colors.primary),
                  const SizedBox(width: 6),
                  Text(
                    '${_fmt(dateFrom)} — ${_fmt(dateTo)}',
                    style: TextStyle(
                        color: colors.text,
                        fontSize: 13,
                        fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(width: 4),
                  Icon(Icons.arrow_drop_down,
                      size: 18, color: colors.text3),
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),
          // Status filter chips
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: [
                _StatusChip(
                  label: 'Все',
                  selected: statusFilter == null,
                  onTap: () => onStatusChanged(null),
                  colors: colors,
                ),
                const SizedBox(width: 6),
                _StatusChip(
                  label: 'Оплачено',
                  selected: statusFilter == 'paid',
                  onTap: () => onStatusChanged('paid'),
                  colors: colors,
                ),
                const SizedBox(width: 6),
                _StatusChip(
                  label: 'Ожидает',
                  selected: statusFilter == 'pending',
                  onTap: () => onStatusChanged('pending'),
                  colors: colors,
                ),
                const SizedBox(width: 6),
                _StatusChip(
                  label: 'Отменено',
                  selected: statusFilter == 'cancelled',
                  onTap: () => onStatusChanged('cancelled'),
                  colors: colors,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _StatusChip extends StatelessWidget {
  const _StatusChip({
    required this.label,
    required this.selected,
    required this.onTap,
    required this.colors,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;
  final AppColors colors;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: selected ? colors.primary : colors.bg2,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(
            color: selected ? colors.primary : colors.border,
          ),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w600,
            color: selected ? Colors.white : colors.text2,
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Summary cards
// ---------------------------------------------------------------------------

class _SummaryCards extends StatelessWidget {
  const _SummaryCards({required this.report, required this.colors});

  final PaymentReport report;
  final AppColors colors;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      child: Row(
        children: [
          Expanded(
            child: _StatCard(
              label: 'Оплачено',
              value: '${_fmt(report.totalPaid)} ₽',
              color: colors.green,
              colors: colors,
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: _StatCard(
              label: 'Ожидает',
              value: '${_fmt(report.totalPending)} ₽',
              color: colors.primary,
              colors: colors,
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: _StatCard(
              label: 'Всего',
              value: '${report.count}',
              color: colors.text2,
              colors: colors,
            ),
          ),
        ],
      ),
    );
  }

  String _fmt(double v) {
    if (v >= 1000000) {
      return '${(v / 1000000).toStringAsFixed(1)} млн';
    }
    if (v >= 1000) {
      return '${(v / 1000).toStringAsFixed(1)} тыс';
    }
    return v.toStringAsFixed(0);
  }
}

class _StatCard extends StatelessWidget {
  const _StatCard({
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
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: colors.bg2,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: colors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: TextStyle(fontSize: 11, color: colors.text3),
          ),
          const SizedBox(height: 4),
          Text(
            value,
            style: TextStyle(
              fontSize: 15,
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
// Payment card
// ---------------------------------------------------------------------------

class _PaymentCard extends StatelessWidget {
  const _PaymentCard({required this.payment, required this.colors});

  final Payment payment;
  final AppColors colors;

  static const _statusLabels = <String, String>{
    'paid': 'Оплачено',
    'pending': 'Ожидает',
    'cancelled': 'Отменено',
    'refunded': 'Возврат',
  };

  static const _kindLabels = <String, String>{
    'prepayment': 'Предоплата',
    'delivery': 'Доставка',
    'invoice': 'Счёт',
    'adjustment': 'Корректировка',
  };

  static const _methodLabels = <String, String>{
    'cash': 'Наличные',
    'card': 'Карта',
    'bank_transfer': 'Перевод',
  };

  String _fmtDate(DateTime? d) {
    if (d == null) return '—';
    return '${d.day.toString().padLeft(2, '0')}.${d.month.toString().padLeft(2, '0')}.${d.year}';
  }

  @override
  Widget build(BuildContext context) {
    final isPaid = payment.status == 'paid';
    final statusColor = isPaid ? colors.green : colors.red;
    final statusLabel =
        _statusLabels[payment.status] ?? payment.status;

    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      decoration: BoxDecoration(
        color: colors.bg2,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: colors.border),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header row: amount + status badge
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  '${payment.amount.toStringAsFixed(0)} ₽',
                  style: TextStyle(
                    fontSize: 17,
                    fontWeight: FontWeight.w700,
                    color: colors.text,
                  ),
                ),
                _Badge(
                  label: statusLabel,
                  color: statusColor,
                ),
              ],
            ),
            const SizedBox(height: 6),
            // Kind + method
            Row(
              children: [
                _InfoChip(
                  label: _kindLabels[payment.kind] ?? payment.kind,
                  colors: colors,
                ),
                if (payment.method != null) ...[
                  const SizedBox(width: 6),
                  _InfoChip(
                    label: _methodLabels[payment.method!] ??
                        payment.method!,
                    colors: colors,
                  ),
                ],
              ],
            ),
            const SizedBox(height: 8),
            Divider(height: 1, color: colors.border),
            const SizedBox(height: 8),
            // Dates row
            Row(
              children: [
                Expanded(
                  child: _LabelValue(
                    label: 'Создан',
                    value: _fmtDate(payment.createdAt),
                    colors: colors,
                  ),
                ),
                Expanded(
                  child: _LabelValue(
                    label: 'Оплачен',
                    value: _fmtDate(payment.paidAt),
                    colors: colors,
                  ),
                ),
              ],
            ),
            // Invoice number if available
            if (payment.invoiceNumber != null &&
                payment.invoiceNumber!.isNotEmpty) ...[
              const SizedBox(height: 4),
              _LabelValue(
                label: 'Счёт №',
                value: payment.invoiceNumber!,
                colors: colors,
              ),
            ],
            if (payment.notes != null &&
                payment.notes!.isNotEmpty) ...[
              const SizedBox(height: 4),
              _LabelValue(
                label: 'Примечание',
                value: payment.notes!,
                colors: colors,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _Badge extends StatelessWidget {
  const _Badge({required this.label, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
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

class _InfoChip extends StatelessWidget {
  const _InfoChip({required this.label, required this.colors});

  final String label;
  final AppColors colors;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: colors.bg3,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        label,
        style: TextStyle(fontSize: 11, color: colors.text2),
      ),
    );
  }
}

class _LabelValue extends StatelessWidget {
  const _LabelValue({
    required this.label,
    required this.value,
    required this.colors,
  });

  final String label;
  final String value;
  final AppColors colors;

  @override
  Widget build(BuildContext context) {
    return RichText(
      text: TextSpan(
        children: [
          TextSpan(
            text: '$label: ',
            style: TextStyle(
                fontSize: 12,
                color: colors.text3),
          ),
          TextSpan(
            text: value,
            style: TextStyle(
                fontSize: 12,
                color: colors.text,
                fontWeight: FontWeight.w500),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Error / retry
// ---------------------------------------------------------------------------

class _ErrorRetry extends StatelessWidget {
  const _ErrorRetry({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        const SizedBox(height: 80),
        Text(message, textAlign: TextAlign.center),
        const SizedBox(height: 12),
        OutlinedButton(
          onPressed: onRetry,
          child: const Text('Повторить'),
        ),
      ],
    );
  }
}
