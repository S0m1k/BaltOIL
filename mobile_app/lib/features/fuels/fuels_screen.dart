import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../auth/auth_repository.dart';
import '../orders/order_models.dart';
import '../orders/orders_repository.dart';

/// Справочник топлива (веб pane-fuels): карточки код/название/зимнее.
/// Просмотр — всем ролям; admin (правки 2026-07-14) видит и скрытые виды,
/// может добавлять, переименовывать и скрывать (глазик).
class FuelsScreen extends StatefulWidget {
  const FuelsScreen({super.key, required this.user});

  final CurrentUser user;

  @override
  State<FuelsScreen> createState() => _FuelsScreenState();
}

/// Код вида из названия: транслит → [a-z0-9_] (зеркало _fuelCodeFromLabel
/// веба — бэкенд требует такой паттерн).
String fuelCodeFromLabel(String label) {
  const map = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
  };
  final translit = label
      .toLowerCase()
      .split('')
      .map((ch) => map[ch] ?? ch)
      .join();
  final code = translit
      .replaceAll(RegExp(r'[^a-z0-9]+'), '_')
      .replaceAll(RegExp(r'^_+|_+$'), '');
  final trimmed = code.length > 50 ? code.substring(0, 50) : code;
  return trimmed.isEmpty ? 'fuel' : trimmed;
}

class _FuelsScreenState extends State<FuelsScreen> {
  late Future<List<FuelType>> _future;

  bool get _isAdmin => widget.user.role == 'admin';

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    setState(() {
      // Админ видит и скрытые виды (глазик), остальные — только активные.
      _future = OrdersRepository.instance
          .fuelTypes(includeInactive: _isAdmin);
    });
  }

  void _snack(String message, {bool isError = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(message),
      backgroundColor: isError ? Colors.red.shade700 : null,
    ));
  }

  Future<void> _addFuel() async {
    final labelCtrl = TextEditingController();
    bool isWinter = false;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          title: const Text('Новый вид топлива'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: labelCtrl,
                autofocus: true,
                decoration: const InputDecoration(
                  labelText: 'Название *',
                  hintText: 'АИ-98',
                ),
              ),
              const SizedBox(height: 8),
              CheckboxListTile(
                value: isWinter,
                onChanged: (v) =>
                    setDialogState(() => isWinter = v ?? false),
                contentPadding: EdgeInsets.zero,
                title: const Text('Зимнее топливо',
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
              child: const Text('Добавить'),
            ),
          ],
        ),
      ),
    );
    if (ok != true) return;
    final label = labelCtrl.text.trim();
    if (label.isEmpty) {
      _snack('Укажите название', isError: true);
      return;
    }
    try {
      await OrdersRepository.instance.createFuelType(
        code: fuelCodeFromLabel(label),
        label: label,
        isWinter: isWinter,
      );
      _snack('Вид топлива добавлен');
      _load();
    } on Object catch (e) {
      _snack(apiErrorMessage(e), isError: true);
    }
  }

  Future<void> _renameFuel(FuelType fuel) async {
    final labelCtrl = TextEditingController(text: fuel.label);
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Переименовать вид топлива'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              controller: labelCtrl,
              autofocus: true,
              decoration: const InputDecoration(labelText: 'Название'),
            ),
            const SizedBox(height: 10),
            Text(
              'Код останется ${fuel.code} — исторические заявки не пострадают.',
              style: const TextStyle(fontSize: 11, color: Colors.grey),
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
    );
    if (ok != true) return;
    final label = labelCtrl.text.trim();
    if (label.isEmpty) {
      _snack('Укажите название', isError: true);
      return;
    }
    try {
      await OrdersRepository.instance.updateFuelType(fuel.code, label: label);
      _snack('Переименовано');
      _load();
    } on Object catch (e) {
      _snack(apiErrorMessage(e), isError: true);
    }
  }

  Future<void> _toggleVisibility(FuelType fuel) async {
    try {
      await OrdersRepository.instance
          .updateFuelType(fuel.code, isActive: !fuel.isActive);
      _snack(fuel.isActive
          ? 'Скрыто — не будет в заявках и тарифах'
          : 'Снова доступно');
      _load();
    } on Object catch (e) {
      _snack(apiErrorMessage(e), isError: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      floatingActionButton: _isAdmin
          ? FloatingActionButton.extended(
              onPressed: _addFuel,
              icon: const Icon(Icons.add),
              label: const Text('Вид топлива'),
            )
          : null,
      body: RefreshIndicator(
        onRefresh: () async => _load(),
        child: FutureBuilder<List<FuelType>>(
          future: _future,
          builder: (context, snap) {
            if (snap.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snap.hasError) {
              return ListView(children: [
                const SizedBox(height: 100),
                Center(child: Text(apiErrorMessage(snap.error!))),
                Center(
                  child: TextButton(
                      onPressed: _load, child: const Text('Повторить')),
                ),
              ]);
            }
            final fuels = snap.data ?? const [];
            if (fuels.isEmpty) {
              return ListView(children: const [
                SizedBox(height: 120),
                Center(child: Text('Справочник топлива пуст')),
              ]);
            }
            return GridView.builder(
              padding: const EdgeInsets.all(12),
              gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
                maxCrossAxisExtent: 240,
                mainAxisSpacing: 12,
                crossAxisSpacing: 12,
                childAspectRatio: 1.4,
              ),
              itemCount: fuels.length,
              itemBuilder: (context, i) => _FuelCard(
                fuel: fuels[i],
                isAdmin: _isAdmin,
                theme: theme,
                onRename: () => _renameFuel(fuels[i]),
                onToggle: () => _toggleVisibility(fuels[i]),
              ),
            );
          },
        ),
      ),
    );
  }
}

class _FuelCard extends StatelessWidget {
  const _FuelCard({
    required this.fuel,
    required this.isAdmin,
    required this.theme,
    required this.onRename,
    required this.onToggle,
  });

  final FuelType fuel;
  final bool isAdmin;
  final ThemeData theme;
  final VoidCallback onRename;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    return Opacity(
      opacity: fuel.isActive ? 1 : 0.45,
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(fuel.code,
                        style: theme.textTheme.titleMedium
                            ?.copyWith(fontWeight: FontWeight.w700),
                        overflow: TextOverflow.ellipsis),
                  ),
                  if (isAdmin)
                    InkWell(
                      onTap: onRename,
                      borderRadius: BorderRadius.circular(4),
                      child: const Padding(
                        padding: EdgeInsets.all(4),
                        child: Icon(Icons.edit_outlined, size: 16),
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 4),
              Text(fuel.label,
                  style: theme.textTheme.bodySmall,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis),
              Wrap(
                spacing: 8,
                children: [
                  if (fuel.isWinter)
                    Text('зимнее',
                        style: theme.textTheme.bodySmall
                            ?.copyWith(color: theme.colorScheme.primary)),
                  if (!fuel.isActive)
                    Text('скрыто',
                        style: theme.textTheme.bodySmall
                            ?.copyWith(color: theme.colorScheme.error)),
                ],
              ),
              if (isAdmin) ...[
                const SizedBox(height: 6),
                InkWell(
                  onTap: onToggle,
                  borderRadius: BorderRadius.circular(4),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 4, vertical: 2),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          fuel.isActive
                              ? Icons.visibility_outlined
                              : Icons.visibility_off_outlined,
                          size: 15,
                        ),
                        const SizedBox(width: 4),
                        Text(
                          fuel.isActive ? 'Скрыть' : 'Показать',
                          style: theme.textTheme.bodySmall,
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
