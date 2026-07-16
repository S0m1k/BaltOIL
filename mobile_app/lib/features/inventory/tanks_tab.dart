import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/theme.dart';
import '../orders/order_models.dart';
import '../orders/orders_repository.dart';
import 'inventory_repository.dart';

/// Вкладка «Ёмкости» (веб inv-pane-tanks, правки 2026-07-14):
/// несколько ёмкостей на вид топлива, 6-значный счётчик колонки,
/// журнал было→стало, переливы. Создание/правка/корректировка — admin.
class TanksTab extends StatefulWidget {
  const TanksTab({super.key, required this.isAdmin});

  final bool isAdmin;

  @override
  State<TanksTab> createState() => _TanksTabState();
}

/// Подписи операций журнала — зеркало TANK_TX_LABELS веба.
const _tankTxLabels = {
  'arrival': '▲ Приход',
  'issue': '▼ Выдача',
  'transfer_in': '⇦ Перелив (в)',
  'transfer_out': '⇨ Перелив (из)',
  'adjust': '± Корректировка',
  'expense': '− Расход',
};

class _TanksTabState extends State<TanksTab>
    with AutomaticKeepAliveClientMixin {
  List<Tank>? _tanks;
  List<TankTransaction>? _txs;
  String? _error;
  bool _loading = true;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  Future<void> _reload() async {
    setState(() {
      _loading = _tanks == null;
      _error = null;
    });
    try {
      final tanks = await InventoryRepository.instance
          .listTanks(includeInactive: widget.isAdmin);
      final txs =
          await InventoryRepository.instance.listTankTransactions();
      if (!mounted) return;
      setState(() {
        _tanks = tanks;
        _txs = txs;
        _loading = false;
      });
    } on Object catch (e) {
      if (!mounted) return;
      setState(() {
        _error = apiErrorMessage(e);
        _loading = false;
      });
    }
  }

  void _snack(String message, {bool isError = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(message),
      backgroundColor: isError ? Colors.red.shade700 : null,
    ));
  }

  Future<List<FuelType>> _activeFuels() async {
    final fuels = await OrdersRepository.instance.fuelTypes();
    return fuels;
  }

  // ── Диалоги (зеркала promptCreateTank / promptEditTank / …) ───────

  Future<void> _createTank() async {
    final fuels = await _activeFuels();
    if (!mounted || fuels.isEmpty) return;
    final nameCtrl = TextEditingController();
    final volumeCtrl = TextEditingController(text: '0');
    final counterCtrl = TextEditingController(text: '0');
    String fuel = fuels.first.code;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          title: const Text('Новая ёмкость'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: nameCtrl,
                  autofocus: true,
                  decoration: const InputDecoration(
                    labelText: 'Название *',
                    hintText: 'Ёмкость №1',
                  ),
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue: fuel,
                  items: [
                    for (final f in fuels)
                      DropdownMenuItem(value: f.code, child: Text(f.label)),
                  ],
                  onChanged: (v) =>
                      setDialogState(() => fuel = v ?? fuel),
                  decoration:
                      const InputDecoration(labelText: 'Вид топлива'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: volumeCtrl,
                  keyboardType: const TextInputType.numberWithOptions(
                      decimal: true),
                  decoration: const InputDecoration(
                      labelText: 'Начальный остаток, л'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: counterCtrl,
                  keyboardType: TextInputType.number,
                  maxLength: 6,
                  decoration: const InputDecoration(
                    labelText: 'Счётчик (6 цифр)',
                    hintText: '229523',
                    counterText: '',
                  ),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: const Text('Отмена'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(ctx).pop(true),
              child: const Text('Создать'),
            ),
          ],
        ),
      ),
    );
    if (ok != true) return;
    final name = nameCtrl.text.trim();
    if (name.isEmpty) {
      _snack('Укажите название', isError: true);
      return;
    }
    final counter = int.tryParse(counterCtrl.text.trim()) ?? 0;
    if (counter < 0 || counter > 999999) {
      _snack('Счётчик — число от 0 до 999999', isError: true);
      return;
    }
    try {
      await InventoryRepository.instance.createTank(
        name: name,
        fuelType: fuel,
        initialVolume: double.tryParse(
                volumeCtrl.text.trim().replaceAll(',', '.')) ??
            0,
        counter: counter,
      );
      _snack('Ёмкость создана');
      await _reload();
    } on Object catch (e) {
      _snack(apiErrorMessage(e), isError: true);
    }
  }

  Future<void> _editTank(Tank tank) async {
    final fuels = await _activeFuels();
    if (!mounted) return;
    final nameCtrl = TextEditingController(text: tank.name);
    String fuel = tank.fuelType;
    // Скрытый вид топлива ёмкости добавляем в опции, чтобы селект не падал.
    final options = [
      for (final f in fuels) (f.code, f.label),
      if (!fuels.any((f) => f.code == tank.fuelType))
        (tank.fuelType, tank.fuelLabel ?? tank.fuelType),
    ];
    bool isActive = tank.isActive;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          title: Text('Ёмкость: ${tank.name}'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: nameCtrl,
                decoration: const InputDecoration(labelText: 'Название'),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                initialValue: fuel,
                items: [
                  for (final (code, label) in options)
                    DropdownMenuItem(value: code, child: Text(label)),
                ],
                onChanged: (v) => setDialogState(() => fuel = v ?? fuel),
                decoration:
                    const InputDecoration(labelText: 'Вид топлива'),
              ),
              const SizedBox(height: 8),
              CheckboxListTile(
                value: isActive,
                onChanged: (v) =>
                    setDialogState(() => isActive = v ?? true),
                contentPadding: EdgeInsets.zero,
                title: const Text('Ёмкость активна (видна в операциях)',
                    style: TextStyle(fontSize: 14)),
                controlAffinity: ListTileControlAffinity.leading,
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
              child: const Text('Сохранить'),
            ),
          ],
        ),
      ),
    );
    if (ok != true) return;
    final name = nameCtrl.text.trim();
    if (name.isEmpty) {
      _snack('Укажите название', isError: true);
      return;
    }
    try {
      await InventoryRepository.instance.updateTank(
        tank.id,
        name: name,
        fuelType: fuel,
        isActive: isActive,
      );
      _snack('Сохранено');
      await _reload();
    } on Object catch (e) {
      _snack(apiErrorMessage(e), isError: true);
    }
  }

  Future<void> _adjustTank(Tank tank) async {
    final volumeCtrl =
        TextEditingController(text: tank.currentVolume.toString());
    final counterCtrl = TextEditingController(text: tank.counter.toString());
    final notesCtrl = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Корректировка: ${tank.name}'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: volumeCtrl,
              keyboardType: const TextInputType.numberWithOptions(
                  decimal: true, signed: true),
              decoration: const InputDecoration(labelText: 'Остаток, л'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: counterCtrl,
              keyboardType: TextInputType.number,
              maxLength: 6,
              decoration: const InputDecoration(
                labelText: 'Счётчик (6 цифр)',
                counterText: '',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: notesCtrl,
              decoration: const InputDecoration(
                labelText: 'Причина *',
                hintText: 'Сверка, ошибка ввода...',
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
            child: const Text('Записать'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    final notes = notesCtrl.text.trim();
    if (notes.isEmpty) {
      _snack('Укажите причину', isError: true);
      return;
    }
    final counter = int.tryParse(counterCtrl.text.trim());
    if (counter == null || counter < 0 || counter > 999999) {
      _snack('Счётчик — число от 0 до 999999', isError: true);
      return;
    }
    try {
      await InventoryRepository.instance.adjustTank(
        tank.id,
        volume:
            double.tryParse(volumeCtrl.text.trim().replaceAll(',', '.')),
        counter: counter,
        notes: notes,
      );
      _snack('Корректировка записана');
      await _reload();
    } on Object catch (e) {
      _snack(apiErrorMessage(e), isError: true);
    }
  }

  Future<void> _tankArrival(Tank tank) async {
    final volumeCtrl = TextEditingController();
    final notesCtrl = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Приход в ёмкость: ${tank.name}'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: volumeCtrl,
              autofocus: true,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                labelText: 'Сколько добавили, л *',
                hintText: '10000',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: notesCtrl,
              decoration: const InputDecoration(
                labelText: 'Примечание',
                hintText: 'Поставщик, накладная...',
              ),
            ),
            const SizedBox(height: 10),
            const Text(
              'Изменить запись после отправки нельзя — ошибку исправляет '
              'администратор корректировкой.',
              style: TextStyle(fontSize: 11, color: Colors.grey),
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
            child: const Text('Записать'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    final volume =
        double.tryParse(volumeCtrl.text.trim().replaceAll(',', '.'));
    if (volume == null || volume <= 0) {
      _snack('Укажите объём', isError: true);
      return;
    }
    try {
      await InventoryRepository.instance.tankArrival(
        tank.id,
        volume: volume,
        notes: notesCtrl.text.trim(),
      );
      _snack('Приход записан');
      await _reload();
    } on Object catch (e) {
      _snack(apiErrorMessage(e), isError: true);
    }
  }

  Future<void> _transfer() async {
    final active =
        (_tanks ?? const <Tank>[]).where((t) => t.isActive).toList();
    if (active.length < 2) {
      _snack('Нужно минимум две ёмкости', isError: true);
      return;
    }
    String fromId = active[0].id;
    String toId = active[1].id;
    final volumeCtrl = TextEditingController();
    final notesCtrl = TextEditingController();
    String optLabel(Tank t) =>
        '${t.name} · ${t.fuelLabel ?? t.fuelType} · ${t.currentVolume.toStringAsFixed(0)} л';
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          title: const Text('Перелив между ёмкостями'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                DropdownButtonFormField<String>(
                  initialValue: fromId,
                  isExpanded: true,
                  items: [
                    for (final t in active)
                      DropdownMenuItem(
                        value: t.id,
                        child: Text(optLabel(t),
                            overflow: TextOverflow.ellipsis),
                      ),
                  ],
                  onChanged: (v) =>
                      setDialogState(() => fromId = v ?? fromId),
                  decoration:
                      const InputDecoration(labelText: 'Из ёмкости'),
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue: toId,
                  isExpanded: true,
                  items: [
                    for (final t in active)
                      DropdownMenuItem(
                        value: t.id,
                        child: Text(optLabel(t),
                            overflow: TextOverflow.ellipsis),
                      ),
                  ],
                  onChanged: (v) => setDialogState(() => toId = v ?? toId),
                  decoration:
                      const InputDecoration(labelText: 'В ёмкость'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: volumeCtrl,
                  keyboardType: const TextInputType.numberWithOptions(
                      decimal: true),
                  decoration: const InputDecoration(
                    labelText: 'Объём, л *',
                    hintText: '1000',
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: notesCtrl,
                  decoration:
                      const InputDecoration(labelText: 'Примечание'),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: const Text('Отмена'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(ctx).pop(true),
              child: const Text('Перелить'),
            ),
          ],
        ),
      ),
    );
    if (ok != true) return;
    if (fromId == toId) {
      _snack('Выберите две разные ёмкости', isError: true);
      return;
    }
    final volume =
        double.tryParse(volumeCtrl.text.trim().replaceAll(',', '.'));
    if (volume == null || volume <= 0) {
      _snack('Укажите объём', isError: true);
      return;
    }
    try {
      await InventoryRepository.instance.tankTransfer(
        fromTankId: fromId,
        toTankId: toId,
        volume: volume,
        notes: notesCtrl.text.trim(),
      );
      _snack('Перелив записан');
      await _reload();
    } on Object catch (e) {
      _snack(apiErrorMessage(e), isError: true);
    }
  }

  // ── UI ─────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final colors = context.colors;
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null && _tanks == null) {
      return ListView(children: [
        const SizedBox(height: 100),
        Center(child: Text(_error!, textAlign: TextAlign.center)),
        const SizedBox(height: 12),
        Center(
          child: OutlinedButton(
            onPressed: _reload,
            child: const Text('Повторить'),
          ),
        ),
      ]);
    }
    final tanks = _tanks ?? const <Tank>[];
    final txs = _txs ?? const <TankTransaction>[];
    return RefreshIndicator(
      onRefresh: _reload,
      child: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          Row(
            children: [
              if (widget.isAdmin)
                OutlinedButton.icon(
                  onPressed: _createTank,
                  icon: const Icon(Icons.add, size: 18),
                  label: const Text('Ёмкость'),
                ),
              if (widget.isAdmin) const SizedBox(width: 8),
              OutlinedButton.icon(
                onPressed: _transfer,
                icon: const Icon(Icons.swap_horiz, size: 18),
                label: const Text('Перелив'),
              ),
            ],
          ),
          const SizedBox(height: 12),
          if (tanks.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 40),
              child: Center(
                child: Text(
                  'Ёмкостей пока нет'
                  '${widget.isAdmin ? ' — создайте первую кнопкой «+ Ёмкость»' : ''}',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: colors.text3),
                ),
              ),
            )
          else
            for (final t in tanks)
              _TankCard(
                tank: t,
                colors: colors,
                isAdmin: widget.isAdmin,
                onArrival: () => _tankArrival(t),
                onEdit: () => _editTank(t),
                onAdjust: () => _adjustTank(t),
              ),
          const SizedBox(height: 16),
          Text(
            'Журнал операций',
            style: TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w700,
              color: colors.text,
            ),
          ),
          const SizedBox(height: 8),
          if (txs.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 20),
              child: Center(
                child: Text('Операций пока нет',
                    style: TextStyle(color: colors.text3)),
              ),
            )
          else
            for (final tx in txs) _TankTxCard(tx: tx, colors: colors),
        ],
      ),
    );
  }
}

class _TankCard extends StatelessWidget {
  const _TankCard({
    required this.tank,
    required this.colors,
    required this.isAdmin,
    required this.onArrival,
    required this.onEdit,
    required this.onAdjust,
  });

  final Tank tank;
  final AppColors colors;
  final bool isAdmin;
  final VoidCallback onArrival;
  final VoidCallback onEdit;
  final VoidCallback onAdjust;

  @override
  Widget build(BuildContext context) {
    final isNegative = tank.currentVolume < 0;
    return Opacity(
      opacity: tank.isActive ? 1 : 0.45,
      child: Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: colors.bg2,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: colors.border),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 6,
              runSpacing: 4,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text(
                  tank.name,
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                    color: colors.text,
                  ),
                ),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
                  decoration: BoxDecoration(
                    border: Border.all(color: colors.border),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    tank.fuelLabel ?? tank.fuelType,
                    style: TextStyle(fontSize: 10, color: colors.text3),
                  ),
                ),
                if (!tank.isActive)
                  Text('скрыта',
                      style: TextStyle(fontSize: 10, color: colors.red)),
              ],
            ),
            const SizedBox(height: 6),
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(
                  tank.currentVolume.toStringAsFixed(0),
                  style: TextStyle(
                    fontSize: 22,
                    fontWeight: FontWeight.w700,
                    color: isNegative ? colors.red : colors.text,
                  ),
                ),
                const SizedBox(width: 4),
                Padding(
                  padding: const EdgeInsets.only(bottom: 3),
                  child: Text('л',
                      style: TextStyle(fontSize: 13, color: colors.text3)),
                ),
              ],
            ),
            const SizedBox(height: 2),
            Text(
              'Счётчик: ${tank.counterText}',
              style: TextStyle(
                fontSize: 13,
                fontFamily: 'monospace',
                color: colors.text2,
              ),
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 6,
              children: [
                OutlinedButton(
                  onPressed: onArrival,
                  style: OutlinedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(horizontal: 10),
                    minimumSize: const Size(0, 34),
                  ),
                  child: const Text('+ Приход',
                      style: TextStyle(fontSize: 12)),
                ),
                if (isAdmin)
                  OutlinedButton(
                    onPressed: onEdit,
                    style: OutlinedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(horizontal: 10),
                      minimumSize: const Size(0, 34),
                    ),
                    child:
                        const Text('✎', style: TextStyle(fontSize: 13)),
                  ),
                if (isAdmin)
                  OutlinedButton(
                    onPressed: onAdjust,
                    style: OutlinedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(horizontal: 10),
                      minimumSize: const Size(0, 34),
                    ),
                    child:
                        const Text('±', style: TextStyle(fontSize: 13)),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _TankTxCard extends StatelessWidget {
  const _TankTxCard({required this.tx, required this.colors});

  final TankTransaction tx;
  final AppColors colors;

  String _fmtCounter(int? v) =>
      v != null ? v.toString().padLeft(6, '0') : '—';

  String _fmtDate(DateTime d) =>
      '${d.day.toString().padLeft(2, '0')}.${d.month.toString().padLeft(2, '0')}.${d.year} '
      '${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    final label = _tankTxLabels[tx.kind] ?? tx.kind;
    final hasCounters = tx.counterBefore != null || tx.counterAfter != null;
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: colors.bg2,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: colors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Expanded(
                child: Text(
                  '$label · ${tx.tankName ?? ''}'
                  '${tx.peerTankName != null ? ' ⇄ ${tx.peerTankName}' : ''}',
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: colors.text,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              Text(
                '${tx.volume.toStringAsFixed(tx.volume == tx.volume.roundToDouble() ? 0 : 2)} л',
                style: TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                  color: colors.text,
                ),
              ),
            ],
          ),
          const SizedBox(height: 3),
          Text(
            _fmtDate(tx.createdAt) +
                (hasCounters
                    ? ' · счётчик ${_fmtCounter(tx.counterBefore)} → ${_fmtCounter(tx.counterAfter)}'
                    : ''),
            style: TextStyle(
              fontSize: 11,
              fontFamily: hasCounters ? 'monospace' : null,
              color: colors.text3,
            ),
          ),
          if (tx.orderNumber != null || tx.actorName != null)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text(
                [
                  if (tx.orderNumber != null) 'Заявка №${tx.orderNumber}',
                  if (tx.actorName != null) tx.actorName!,
                ].join(' · '),
                style: TextStyle(fontSize: 11, color: colors.text2),
              ),
            ),
          if (tx.notes != null && tx.notes!.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text(
                tx.notes!,
                style: TextStyle(fontSize: 11, color: colors.text3),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
            ),
        ],
      ),
    );
  }
}
