import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/theme.dart';
import '../orders/order_models.dart';
import '../orders/orders_repository.dart';
import 'inventory_repository.dart';

/// Вкладка «− Расход» (веб inv-pane-expense, правки 2026-07-14):
/// ручной расход «в бак / иное» водителем+. Если у вида топлива есть
/// ёмкости — выбор ёмкости обязателен, счётчик после — опционален.
class ExpenseTab extends StatefulWidget {
  const ExpenseTab({super.key});

  @override
  State<ExpenseTab> createState() => _ExpenseTabState();
}

class _ExpenseTabState extends State<ExpenseTab>
    with AutomaticKeepAliveClientMixin {
  List<FuelType> _fuels = const [];
  List<Tank> _tanks = const [];
  bool _loading = true;
  String? _loadError;

  String _kind = 'tank_refuel';
  String? _fuelType;
  String? _tankId;
  final _volumeCtrl = TextEditingController();
  final _counterCtrl = TextEditingController();
  final _notesCtrl = TextEditingController();
  bool _submitting = false;
  String? _errorMsg;
  bool _success = false;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _volumeCtrl.dispose();
    _counterCtrl.dispose();
    _notesCtrl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _loadError = null;
    });
    try {
      final fuels = await OrdersRepository.instance.fuelTypes();
      List<Tank> tanks;
      try {
        tanks = await InventoryRepository.instance.listTanks();
      } on Object {
        tanks = const []; // как на вебе: блок ёмкости просто скрыт
      }
      if (!mounted) return;
      setState(() {
        _fuels = fuels;
        _tanks = tanks.where((t) => t.isActive).toList();
        _fuelType ??= fuels.isNotEmpty ? fuels.first.code : null;
        _syncTankToFuel();
        _loading = false;
      });
    } on Object catch (e) {
      if (!mounted) return;
      setState(() {
        _loadError = apiErrorMessage(e);
        _loading = false;
      });
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

  Tank? get _selectedTank {
    for (final t in _matchingTanks) {
      if (t.id == _tankId) return t;
    }
    return null;
  }

  Future<void> _submit() async {
    setState(() {
      _errorMsg = null;
      _success = false;
    });
    final fuel = _fuelType;
    if (fuel == null) {
      setState(() => _errorMsg = 'Выберите вид топлива');
      return;
    }
    final volume =
        double.tryParse(_volumeCtrl.text.trim().replaceAll(',', '.'));
    if (volume == null || volume <= 0) {
      setState(() => _errorMsg = 'Укажите объём (литры > 0)');
      return;
    }
    final hasTanks = _matchingTanks.isNotEmpty;
    if (hasTanks && _tankId == null) {
      setState(() => _errorMsg = 'Выберите ёмкость');
      return;
    }
    int? counterAfter;
    final counterRaw = _counterCtrl.text.trim();
    if (hasTanks && counterRaw.isNotEmpty) {
      counterAfter = int.tryParse(counterRaw);
      if (counterAfter == null ||
          counterAfter < 0 ||
          counterAfter > 999999) {
        setState(() => _errorMsg = 'Счётчик — число от 0 до 999999');
        return;
      }
    }
    setState(() => _submitting = true);
    try {
      await InventoryRepository.instance.recordExpense(
        fuelType: fuel,
        volume: volume,
        expenseKind: _kind,
        tankId: hasTanks ? _tankId : null,
        counterAfter: counterAfter,
        notes: _notesCtrl.text.trim(),
      );
      _volumeCtrl.clear();
      _counterCtrl.clear();
      _notesCtrl.clear();
      if (mounted) {
        setState(() {
          _success = true;
          _submitting = false;
        });
      }
      // Обновить остатки/счётчики ёмкостей после списания.
      await _load();
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
    final colors = context.colors;
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_loadError != null) {
      return ListView(children: [
        const SizedBox(height: 100),
        Center(child: Text(_loadError!, textAlign: TextAlign.center)),
        const SizedBox(height: 12),
        Center(
          child: OutlinedButton(
            onPressed: _load,
            child: const Text('Повторить'),
          ),
        ),
      ]);
    }
    final matching = _matchingTanks;
    final selected = _selectedTank;
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'Списать топливо (не по заявке)',
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w700,
              color: colors.text,
            ),
          ),
          const SizedBox(height: 16),
          DropdownButtonFormField<String>(
            initialValue: _kind,
            items: const [
              DropdownMenuItem(value: 'tank_refuel', child: Text('В бак')),
              DropdownMenuItem(value: 'other', child: Text('Иное')),
            ],
            onChanged: (v) => setState(() => _kind = v ?? 'tank_refuel'),
            decoration: const InputDecoration(labelText: 'Назначение'),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _fuelType,
            items: [
              for (final f in _fuels)
                DropdownMenuItem(value: f.code, child: Text(f.label)),
            ],
            onChanged: (v) => setState(() {
              _fuelType = v;
              _syncTankToFuel();
            }),
            decoration: const InputDecoration(labelText: 'Вид топлива'),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _volumeCtrl,
            keyboardType:
                const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(
              labelText: 'Объём (литры) *',
              hintText: '200',
              suffixText: 'л',
            ),
          ),
          if (matching.isNotEmpty) ...[
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: _tankId,
              isExpanded: true,
              items: [
                for (final t in matching)
                  DropdownMenuItem(
                    value: t.id,
                    child: Text(
                      '${t.name} · ${t.currentVolume.toStringAsFixed(0)} л · счётчик ${t.counterText}',
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
              ],
              onChanged: (v) => setState(() => _tankId = v),
              decoration:
                  const InputDecoration(labelText: 'Из какой ёмкости *'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _counterCtrl,
              keyboardType: TextInputType.number,
              maxLength: 6,
              decoration: InputDecoration(
                labelText: 'Счётчик после (если лили через колонку)',
                hintText: 'не обязательно',
                counterText: '',
                helperText: selected != null
                    ? 'Текущее показание: ${selected.counterText}. '
                        'Пусто — счётчик не изменится.'
                    : null,
              ),
            ),
          ],
          const SizedBox(height: 12),
          TextField(
            controller: _notesCtrl,
            maxLines: 2,
            decoration: const InputDecoration(
              labelText: 'Комментарий',
              hintText: 'Например: заправка бензовоза №2',
              alignLabelWithHint: true,
            ),
          ),
          const SizedBox(height: 10),
          Text(
            'Запись изменить нельзя — ошибку исправляет администратор '
            'корректировкой. Расход попадает в общий отчёт; «в бак» '
            'выносится отдельной строкой.',
            style: TextStyle(fontSize: 11, color: colors.text3),
          ),
          const SizedBox(height: 16),
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
                  Icon(Icons.check_circle, color: colors.green, size: 18),
                  const SizedBox(width: 6),
                  Text(
                    'Расход записан',
                    style: TextStyle(
                      color: colors.green,
                      fontWeight: FontWeight.w600,
                    ),
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
                : const Text('Списать'),
          ),
        ],
      ),
    );
  }
}
