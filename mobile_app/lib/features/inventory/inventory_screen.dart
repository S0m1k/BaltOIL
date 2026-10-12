import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/theme.dart';
import '../auth/auth_repository.dart';
import '../orders/order_models.dart';
import '../orders/orders_repository.dart';
import 'expense_tab.dart';
import 'inventory_repository.dart';
import 'tanks_tab.dart';

class InventoryScreen extends StatefulWidget {
  const InventoryScreen({super.key, required this.user});

  final CurrentUser user;

  @override
  State<InventoryScreen> createState() => _InventoryScreenState();
}

class _InventoryScreenState extends State<InventoryScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tab;

  bool get _isAdmin => widget.user.role == 'admin';

  @override
  void initState() {
    super.initState();
    // Правки 2026-07-11/14: приход и расход доступны и водителям —
    // журнал append-only, ошибки исправляет админ корректировкой.
    _tab = TabController(length: 5, vsync: this);
  }

  @override
  void dispose() {
    _tab.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Column(
      children: [
        Container(
          color: colors.bg2,
          child: TabBar(
            controller: _tab,
            isScrollable: true,
            tabAlignment: TabAlignment.start,
            labelColor: colors.primary,
            unselectedLabelColor: colors.text3,
            indicatorColor: colors.primary,
            tabs: const [
              Tab(text: 'Остатки'),
              Tab(text: 'Ёмкости'),
              Tab(text: 'Операции'),
              Tab(text: 'Приход'),
              Tab(text: '− Расход'),
            ],
          ),
        ),
        Expanded(
          child: TabBarView(
            controller: _tab,
            children: [
              _StockTab(colors: colors),
              TanksTab(isAdmin: _isAdmin),
              _TransactionsTab(colors: colors),
              _ArrivalTab(colors: colors),
              const ExpenseTab(),
            ],
          ),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Остатки tab
// ---------------------------------------------------------------------------

class _StockTab extends StatefulWidget {
  const _StockTab({required this.colors});

  final AppColors colors;

  @override
  State<_StockTab> createState() => _StockTabState();
}

class _StockTabState extends State<_StockTab>
    with AutomaticKeepAliveClientMixin {
  late Future<List<FuelStock>> _future;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  void _reload() {
    setState(() {
      _future = InventoryRepository.instance.getStock();
    });
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return RefreshIndicator(
      onRefresh: () async => _reload(),
      child: FutureBuilder<List<FuelStock>>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return _ErrorRetry(
              message: apiErrorMessage(snap.error!),
              onRetry: _reload,
            );
          }
          final stocks = snap.data ?? const [];
          if (stocks.isEmpty) {
            return ListView(children: const [
              SizedBox(height: 100),
              Center(child: Text('Нет данных об остатках')),
            ]);
          }
          return ListView.builder(
            padding: const EdgeInsets.all(12),
            itemCount: stocks.length,
            itemBuilder: (ctx, i) => _StockCard(
              stock: stocks[i],
              colors: widget.colors,
            ),
          );
        },
      ),
    );
  }
}

class _StockCard extends StatelessWidget {
  const _StockCard({required this.stock, required this.colors});

  final FuelStock stock;
  final AppColors colors;

  String _fmtDate(DateTime d) =>
      '${d.day.toString().padLeft(2, '0')}.${d.month.toString().padLeft(2, '0')}.${d.year}';

  @override
  Widget build(BuildContext context) {
    final label = FuelCatalog.label(stock.fuelType);
    final volume = stock.currentVolume;
    final isLow = volume < 500;

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: colors.bg2,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: isLow ? colors.red.withValues(alpha: 0.5) : colors.border,
        ),
      ),
      child: Row(
        children: [
          Container(
            width: 48,
            height: 48,
            decoration: BoxDecoration(
              color: colors.accentDim,
              borderRadius: BorderRadius.circular(8),
            ),
            child: Icon(Icons.local_gas_station,
                color: colors.accent, size: 26),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                    color: colors.text,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  'Обновлено: ${_fmtDate(stock.lastUpdated)}',
                  style: TextStyle(fontSize: 11, color: colors.text3),
                ),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                '${volume.toStringAsFixed(0)} л',
                style: TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w700,
                  color: isLow ? colors.red : colors.green,
                ),
              ),
              if (isLow)
                Text(
                  'Мало',
                  style: TextStyle(fontSize: 11, color: colors.red),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Операции tab
// ---------------------------------------------------------------------------

class _TransactionsTab extends StatefulWidget {
  const _TransactionsTab({required this.colors});

  final AppColors colors;

  @override
  State<_TransactionsTab> createState() => _TransactionsTabState();
}

class _TransactionsTabState extends State<_TransactionsTab>
    with AutomaticKeepAliveClientMixin {
  late Future<List<InventoryTransaction>> _future;
  String? _typeFilter; // null | arrival | departure

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  void _reload() {
    setState(() {
      _future = InventoryRepository.instance.listTransactions(
        type: _typeFilter,
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final colors = widget.colors;
    return RefreshIndicator(
      onRefresh: () async => _reload(),
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(
                  children: [
                    _FilterChip(
                      label: 'Все',
                      selected: _typeFilter == null,
                      onTap: () {
                        _typeFilter = null;
                        _reload();
                      },
                      colors: colors,
                    ),
                    const SizedBox(width: 6),
                    _FilterChip(
                      label: 'Приход',
                      selected: _typeFilter == 'arrival',
                      onTap: () {
                        _typeFilter = 'arrival';
                        _reload();
                      },
                      colors: colors,
                    ),
                    const SizedBox(width: 6),
                    _FilterChip(
                      label: 'Расход',
                      selected: _typeFilter == 'departure',
                      onTap: () {
                        _typeFilter = 'departure';
                        _reload();
                      },
                      colors: colors,
                    ),
                  ],
                ),
              ),
            ),
          ),
          FutureBuilderSliver<List<InventoryTransaction>>(
            future: _future,
            onRetry: _reload,
            builder: (txs) {
              if (txs.isEmpty) {
                return const SliverFillRemaining(
                  hasScrollBody: false,
                  child: Center(
                    child: Padding(
                      padding: EdgeInsets.all(32),
                      child: Text('Операций нет'),
                    ),
                  ),
                );
              }
              return SliverList(
                delegate: SliverChildBuilderDelegate(
                  (ctx, i) => _TxCard(tx: txs[i], colors: colors),
                  childCount: txs.length,
                ),
              );
            },
          ),
        ],
      ),
    );
  }
}

class _TxCard extends StatelessWidget {
  const _TxCard({required this.tx, required this.colors});

  final InventoryTransaction tx;
  final AppColors colors;

  String _fmtDate(DateTime d) =>
      '${d.day.toString().padLeft(2, '0')}.${d.month.toString().padLeft(2, '0')}.${d.year}';

  @override
  Widget build(BuildContext context) {
    final isArrival = tx.type == 'arrival';
    final typeColor = isArrival ? colors.green : colors.red;
    final typeLabel = isArrival ? 'Приход' : 'Расход';
    final fuelLabel = FuelCatalog.label(tx.fuelType);

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
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Row(
                  children: [
                    Icon(
                      isArrival
                          ? Icons.arrow_downward
                          : Icons.arrow_upward,
                      size: 16,
                      color: typeColor,
                    ),
                    const SizedBox(width: 4),
                    Text(
                      typeLabel,
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color: typeColor,
                      ),
                    ),
                  ],
                ),
                Text(
                  '${tx.volume.toStringAsFixed(0)} л',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: typeColor,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              fuelLabel,
              style: TextStyle(
                fontSize: 13,
                color: colors.text,
                fontWeight: FontWeight.w500,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              _fmtDate(tx.transactionDate),
              style: TextStyle(fontSize: 12, color: colors.text3),
            ),
            // Arrival context
            if (isArrival && tx.supplierName != null) ...[
              const SizedBox(height: 4),
              Text(
                'Поставщик: ${tx.supplierName}',
                style: TextStyle(fontSize: 12, color: colors.text2),
              ),
            ],
            if (isArrival && tx.invoiceNumber != null) ...[
              const SizedBox(height: 2),
              Text(
                'Накладная: ${tx.invoiceNumber}',
                style: TextStyle(fontSize: 12, color: colors.text2),
              ),
            ],
            // Departure context
            if (!isArrival && tx.orderNumber != null) ...[
              const SizedBox(height: 4),
              Text(
                'Заявка №${tx.orderNumber}',
                style: TextStyle(fontSize: 12, color: colors.text2),
              ),
            ],
            if (!isArrival && tx.driverName != null) ...[
              const SizedBox(height: 2),
              Text(
                'Водитель: ${tx.driverName}',
                style: TextStyle(fontSize: 12, color: colors.text2),
              ),
            ],
            if (tx.notes != null && tx.notes!.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(
                tx.notes!,
                style: TextStyle(fontSize: 11, color: colors.text3),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Приход tab (manager/admin only)
// ---------------------------------------------------------------------------

class _ArrivalTab extends StatefulWidget {
  const _ArrivalTab({required this.colors});

  final AppColors colors;

  @override
  State<_ArrivalTab> createState() => _ArrivalTabState();
}

class _ArrivalTabState extends State<_ArrivalTab>
    with AutomaticKeepAliveClientMixin {
  @override
  bool get wantKeepAlive => true;

  // Form state
  final _formKey = GlobalKey<FormState>();
  String? _fuelType;
  String? _tankId;
  final _volumeCtrl = TextEditingController();
  final _supplierCtrl = TextEditingController();
  final _invoiceCtrl = TextEditingController();
  final _notesCtrl = TextEditingController();
  DateTime? _txDate;
  bool _submitting = false;
  String? _errorMsg;
  bool _success = false;

  // Каталог топлива + ёмкости (правки 2026-07-14): если у вида топлива
  // есть ёмкости — приход обязательно привязывается к одной из них.
  List<(String, String)> _fuelOptions = const [
    ('diesel_summer', 'ДТ-Л К5'),
    ('diesel_winter', 'ДТ-З К5'),
    ('petrol_92', 'АИ-92'),
    ('petrol_95', 'АИ-95'),
    ('fuel_oil', 'М-100'),
  ];
  List<Tank> _tanks = const [];

  @override
  void initState() {
    super.initState();
    _loadCatalogAndTanks();
  }

  Future<void> _loadCatalogAndTanks() async {
    try {
      final fuels = await OrdersRepository.instance.fuelTypes();
      if (fuels.isNotEmpty && mounted) {
        setState(() {
          _fuelOptions = [for (final f in fuels) (f.code, f.label)];
        });
      }
    } on Object {
      // Останется fallback-список — как _FUEL_LABELS_FALLBACK на вебе.
    }
    try {
      final tanks = await InventoryRepository.instance.listTanks();
      if (mounted) {
        setState(() {
          _tanks = tanks.where((t) => t.isActive).toList();
          _syncTankToFuel();
        });
      }
    } on Object {
      // Ёмкостей нет / сервис недоступен — блок просто скрыт.
    }
  }

  List<Tank> get _matchingTanks =>
      _tanks.where((t) => t.fuelType == _fuelType).toList();

  void _syncTankToFuel() {
    final matching = _matchingTanks;
    if (matching.isEmpty) {
      _tankId = null;
    } else if (!matching.any((t) => t.id == _tankId)) {
      _tankId = matching.first.id;
    }
  }

  @override
  void dispose() {
    _volumeCtrl.dispose();
    _supplierCtrl.dispose();
    _invoiceCtrl.dispose();
    _notesCtrl.dispose();
    super.dispose();
  }

  String _fmtDate(DateTime d) =>
      '${d.day.toString().padLeft(2, '0')}.${d.month.toString().padLeft(2, '0')}.${d.year}';

  Future<void> _pickDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _txDate ?? DateTime.now(),
      firstDate: DateTime(2020),
      lastDate: DateTime.now(),
    );
    if (picked == null) return;
    setState(() => _txDate = picked);
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    if (_fuelType == null) {
      setState(() => _errorMsg = 'Выберите вид топлива');
      return;
    }
    final hasTanks = _matchingTanks.isNotEmpty;
    if (hasTanks && _tankId == null) {
      setState(() => _errorMsg = 'Выберите ёмкость');
      return;
    }
    setState(() {
      _submitting = true;
      _errorMsg = null;
      _success = false;
    });
    try {
      final volume = double.parse(_volumeCtrl.text.replaceAll(',', '.'));
      final notes = _notesCtrl.text.trim();
      await InventoryRepository.instance.recordArrival(
        fuelType: _fuelType!,
        volume: volume,
        transactionDate: _txDate,
        supplierName: _supplierCtrl.text.trim(),
        invoiceNumber: _invoiceCtrl.text.trim(),
        notes: notes,
      );
      // Дублируем приход в ёмкость; ошибка не отменяет складскую запись
      // (зеркало doRecordArrival веба).
      if (hasTanks && _tankId != null) {
        try {
          await InventoryRepository.instance
              .tankArrival(_tankId!, volume: volume, notes: notes);
        } on Object catch (te) {
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(SnackBar(
              content: Text(
                  'Склад оприходован, но ёмкость не обновлена: ${apiErrorMessage(te)}'),
              backgroundColor: Colors.red.shade700,
            ));
          }
        }
      }
      _volumeCtrl.clear();
      _supplierCtrl.clear();
      _invoiceCtrl.clear();
      _notesCtrl.clear();
      if (mounted) {
        setState(() {
          _fuelType = null;
          _tankId = null;
          _txDate = null;
          _success = true;
          _submitting = false;
        });
        // Обновить остатки ёмкостей после прихода.
        await _loadCatalogAndTanks();
      }
    } on Object catch (e) {
      if (mounted) {
        setState(() {
          _errorMsg = apiErrorMessage(e);
          _submitting = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final colors = widget.colors;
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Form(
        key: _formKey,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'Приход топлива',
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: colors.text,
              ),
            ),
            const SizedBox(height: 16),

            // Fuel type selector
            Text(
              'Вид топлива',
              style: TextStyle(fontSize: 13, color: colors.text2),
            ),
            const SizedBox(height: 6),
            Container(
              decoration: BoxDecoration(
                color: colors.bg2,
                borderRadius: BorderRadius.circular(6),
                border: Border.all(color: colors.border),
              ),
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: DropdownButtonHideUnderline(
                child: DropdownButton<String>(
                  value: _fuelType,
                  hint: Text('Выберите топливо',
                      style: TextStyle(color: colors.text3)),
                  items: _fuelOptions
                      .map((e) => DropdownMenuItem(
                            value: e.$1,
                            child: Text(e.$2,
                                style: TextStyle(color: colors.text)),
                          ))
                      .toList(),
                  onChanged: (v) => setState(() {
                    _fuelType = v;
                    _syncTankToFuel();
                  }),
                  dropdownColor: colors.bg2,
                  iconEnabledColor: colors.text3,
                ),
              ),
            ),
            const SizedBox(height: 12),

            // Volume
            TextFormField(
              controller: _volumeCtrl,
              keyboardType: const TextInputType.numberWithOptions(
                  decimal: true),
              decoration: const InputDecoration(
                labelText: 'Объём (л)',
                suffixText: 'л',
              ),
              validator: (v) {
                if (v == null || v.trim().isEmpty) {
                  return 'Введите объём';
                }
                final parsed =
                    double.tryParse(v.trim().replaceAll(',', '.'));
                if (parsed == null || parsed <= 0) {
                  return 'Некорректный объём';
                }
                return null;
              },
            ),
            const SizedBox(height: 12),

            // Ёмкость (правки 2026-07-14): обязательна, если у вида
            // топлива заведены ёмкости — приход уходит и в ёмкость.
            if (_matchingTanks.isNotEmpty) ...[
              DropdownButtonFormField<String>(
                initialValue: _tankId,
                isExpanded: true,
                items: [
                  for (final t in _matchingTanks)
                    DropdownMenuItem(
                      value: t.id,
                      child: Text(
                        '${t.name} · ${t.currentVolume.toStringAsFixed(0)} л',
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                ],
                onChanged: (v) => setState(() => _tankId = v),
                decoration:
                    const InputDecoration(labelText: 'В какую ёмкость *'),
              ),
              const SizedBox(height: 12),
            ],

            // Date picker
            GestureDetector(
              onTap: _pickDate,
              child: Container(
                padding: const EdgeInsets.symmetric(
                    horizontal: 12, vertical: 14),
                decoration: BoxDecoration(
                  color: colors.bg2,
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: colors.border),
                ),
                child: Row(
                  children: [
                    Icon(Icons.calendar_today,
                        size: 16, color: colors.text3),
                    const SizedBox(width: 8),
                    Text(
                      _txDate != null
                          ? _fmtDate(_txDate!)
                          : 'Дата операции (сегодня)',
                      style: TextStyle(
                        color: _txDate != null
                            ? colors.text
                            : colors.text3,
                        fontSize: 14,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 12),

            // Supplier
            TextFormField(
              controller: _supplierCtrl,
              decoration: const InputDecoration(
                labelText: 'Поставщик (необязательно)',
              ),
            ),
            const SizedBox(height: 12),

            // Invoice
            TextFormField(
              controller: _invoiceCtrl,
              decoration: const InputDecoration(
                labelText: 'Номер накладной (необязательно)',
              ),
            ),
            const SizedBox(height: 12),

            // Notes
            TextFormField(
              controller: _notesCtrl,
              maxLines: 3,
              decoration: const InputDecoration(
                labelText: 'Примечания (необязательно)',
                alignLabelWithHint: true,
              ),
            ),
            const SizedBox(height: 20),

            if (_errorMsg != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Text(
                  _errorMsg!,
                  style: TextStyle(color: colors.red, fontSize: 13),
                ),
              ),

            if (_success)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Row(
                  children: [
                    Icon(Icons.check_circle,
                        color: colors.green, size: 18),
                    const SizedBox(width: 6),
                    Text(
                      'Приход успешно записан',
                      style: TextStyle(
                          color: colors.green,
                          fontWeight: FontWeight.w600),
                    ),
                  ],
                ),
              ),

            FilledButton(
              onPressed: _submitting ? null : _submit,
              child: _submitting
                  ? const SizedBox(
                      height: 18,
                      width: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white,
                      ),
                    )
                  : const Text('Записать приход'),
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

class _FilterChip extends StatelessWidget {
  const _FilterChip({
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
        padding:
            const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
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

class _ErrorRetry extends StatelessWidget {
  const _ErrorRetry({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return ListView(children: [
      const SizedBox(height: 100),
      Center(
        child: Text(message, textAlign: TextAlign.center),
      ),
      const SizedBox(height: 12),
      Center(
        child: OutlinedButton(
          onPressed: onRetry,
          child: const Text('Повторить'),
        ),
      ),
    ]);
  }
}

/// Sliver-aware FutureBuilder to avoid boilerplate in sliver trees.
class FutureBuilderSliver<T> extends StatelessWidget {
  const FutureBuilderSliver({
    super.key,
    required this.future,
    required this.builder,
    required this.onRetry,
  });

  final Future<T> future;
  final Widget Function(T data) builder;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<T>(
      future: future,
      builder: (ctx, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return const SliverFillRemaining(
            child: Center(child: CircularProgressIndicator()),
          );
        }
        if (snap.hasError) {
          return SliverFillRemaining(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  apiErrorMessage(snap.error!),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 12),
                OutlinedButton(
                  onPressed: onRetry,
                  child: const Text('Повторить'),
                ),
              ],
            ),
          );
        }
        return builder(snap.data as T);
      },
    );
  }
}
