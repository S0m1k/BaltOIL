import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/theme.dart';
import '../auth/auth_repository.dart';
import '../orders/order_models.dart';
import 'tariffs_repository.dart';

// ---------------------------------------------------------------------------
// Screen
// ---------------------------------------------------------------------------

class TariffsScreen extends StatefulWidget {
  const TariffsScreen({super.key, required this.user});

  final CurrentUser user;

  @override
  State<TariffsScreen> createState() => _TariffsScreenState();
}

class _TariffsScreenState extends State<TariffsScreen> {
  late Future<List<Tariff>> _future;
  bool _includeArchived = false;

  bool get _isAdmin => widget.user.role == 'admin';

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    _future = TariffsRepository.instance.list(includeArchived: _includeArchived);
  }

  Future<void> _reload() async {
    final f = TariffsRepository.instance.list(includeArchived: _includeArchived);
    setState(() => _future = f);
    await f;
  }

  Future<void> _setDefault(Tariff tariff) async {
    try {
      await TariffsRepository.instance.setDefault(tariff.id);
      if (!mounted) return;
      _showSnack('Базовый тариф изменён на «${tariff.name}»');
      await _reload();
    } on Exception catch (e) {
      if (!mounted) return;
      _showSnack(apiErrorMessage(e), isError: true);
    }
  }

  Future<void> _archive(Tariff tariff) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Архивировать тариф?'),
        content: Text('«${tariff.name}» будет скрыт из списка активных тарифов.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Отмена'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(
              'Архивировать',
              style: TextStyle(color: context.colors.red),
            ),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await TariffsRepository.instance.archive(tariff.id);
      if (!mounted) return;
      _showSnack('Тариф «${tariff.name}» архивирован');
      await _reload();
    } on Exception catch (e) {
      if (!mounted) return;
      _showSnack(apiErrorMessage(e), isError: true);
    }
  }

  Future<void> _showCreateDialog() async {
    final result = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (ctx) => _CreateTariffSheet(onCreated: () => Navigator.pop(ctx, true)),
    );
    if (result == true) await _reload();
  }

  void _showSnack(String message, {bool isError = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: isError ? context.colors.red : null,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Column(
      children: [
        // Toolbar: archived toggle + create button (admin-only)
        Container(
          color: colors.bg,
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          child: Row(
            children: [
              Text(
                'Тарифы',
                style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: colors.text,
                ),
              ),
              const Spacer(),
              _ArchivedToggle(
                value: _includeArchived,
                onChanged: (v) {
                  setState(() => _includeArchived = v);
                  _reload();
                },
              ),
              if (_isAdmin) ...[
                const SizedBox(width: 8),
                FilledButton.icon(
                  onPressed: _showCreateDialog,
                  icon: const Icon(Icons.add, size: 16),
                  label: const Text('Новый'),
                  style: FilledButton.styleFrom(
                    visualDensity: VisualDensity.compact,
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  ),
                ),
              ],
            ],
          ),
        ),
        Divider(height: 1, color: colors.border),
        // List
        Expanded(
          child: RefreshIndicator(
            onRefresh: _reload,
            child: FutureBuilder<List<Tariff>>(
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
                final tariffs = snap.data ?? const [];
                if (tariffs.isEmpty) {
                  return ListView(
                    children: const [
                      SizedBox(height: 120),
                      Center(child: Text('Тарифов пока нет')),
                    ],
                  );
                }
                return ListView.separated(
                  padding: const EdgeInsets.all(12),
                  itemCount: tariffs.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 10),
                  itemBuilder: (context, i) => _TariffCard(
                    tariff: tariffs[i],
                    isAdmin: _isAdmin,
                    onSetDefault: () => _setDefault(tariffs[i]),
                    onArchive: () => _archive(tariffs[i]),
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
// Archived toggle chip
// ---------------------------------------------------------------------------

class _ArchivedToggle extends StatelessWidget {
  const _ArchivedToggle({required this.value, required this.onChanged});

  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => onChanged(!value),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(
          color: value
              ? context.colors.primaryDim
              : context.colors.bg2,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: context.colors.border),
        ),
        child: Text(
          'С архивом',
          style: TextStyle(
            fontSize: 12,
            color: value ? context.colors.primary : context.colors.text3,
            fontWeight: FontWeight.w500,
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Tariff card
// ---------------------------------------------------------------------------

class _TariffCard extends StatelessWidget {
  const _TariffCard({
    required this.tariff,
    required this.isAdmin,
    required this.onSetDefault,
    required this.onArchive,
  });

  final Tariff tariff;
  final bool isAdmin;
  final VoidCallback onSetDefault;
  final VoidCallback onArchive;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final isStaff = isAdmin; // manager is read-only; only admin triggers actions

    return Container(
      decoration: BoxDecoration(
        color: colors.bg2,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: tariff.isDefault ? colors.accent : colors.border,
          width: tariff.isDefault ? 1.5 : 1,
        ),
      ),
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header: name + badges + action buttons
          Row(
            children: [
              Expanded(
                child: Text(
                  tariff.name,
                  style: TextStyle(
                    fontWeight: FontWeight.w600,
                    fontSize: 15,
                    color: colors.text,
                  ),
                ),
              ),
              if (tariff.isDefault)
                _Badge(label: 'Базовый', bg: colors.accentDim, fg: colors.accent),
              if (tariff.isArchived) ...[
                const SizedBox(width: 6),
                _Badge(label: 'Архив', bg: colors.bg3, fg: colors.text3),
              ],
            ],
          ),
          // Description
          if (tariff.description != null && tariff.description!.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              tariff.description!,
              style: TextStyle(fontSize: 12, color: colors.text3),
            ),
          ],
          // Client type tag
          if (tariff.clientType != null) ...[
            const SizedBox(height: 4),
            Text(
              _clientTypeLabel(tariff.clientType!),
              style: TextStyle(fontSize: 12, color: colors.text3),
            ),
          ],
          const SizedBox(height: 10),
          // Fuel prices
          if (tariff.fuelPrices.isNotEmpty)
            Wrap(
              spacing: 8,
              runSpacing: 6,
              children: tariff.fuelPrices.map((fp) => _FuelPriceChip(fp)).toList(),
            ),
          // Delivery cost
          const SizedBox(height: 6),
          Text(
            'Доставка: ${tariff.baseDeliveryCost.toStringAsFixed(2)} ₽/л',
            style: TextStyle(fontSize: 12, color: colors.text3),
          ),
          // Volume tiers
          if (tariff.volumeTiers.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              'Скидки: ${tariff.volumeTiers.map((t) => 'от ${_formatVolume(t.minVolume)} л → ${t.discountPct.toStringAsFixed(0)}%').join(', ')}',
              style: TextStyle(fontSize: 12, color: colors.text3),
            ),
          ],
          // Admin action buttons
          if (isStaff && !tariff.isArchived) ...[
            const SizedBox(height: 12),
            Row(
              children: [
                if (!tariff.isDefault)
                  _ActionButton(
                    label: 'Сделать базовым',
                    onTap: onSetDefault,
                    color: colors.accent,
                  ),
                if (!tariff.isDefault) const SizedBox(width: 8),
                if (!tariff.isDefault)
                  _ActionButton(
                    label: 'Архивировать',
                    onTap: onArchive,
                    color: colors.red,
                  ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  static String _clientTypeLabel(String type) => switch (type) {
        'individual' => 'Физические лица',
        'company' => 'Юридические лица',
        _ => type,
      };

  static String _formatVolume(double v) {
    if (v >= 1000) {
      return '${(v / 1000).toStringAsFixed(v % 1000 == 0 ? 0 : 1)} тыс.';
    }
    return v.toStringAsFixed(0);
  }
}

// ---------------------------------------------------------------------------
// Fuel price chip
// ---------------------------------------------------------------------------

class _FuelPriceChip extends StatelessWidget {
  const _FuelPriceChip(this.fp);

  final TariffFuelPrice fp;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: colors.bg3,
        borderRadius: BorderRadius.circular(4),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            FuelCatalog.label(fp.fuelType),
            style: TextStyle(fontSize: 12, color: colors.text3),
          ),
          const SizedBox(width: 6),
          Text(
            '${fp.pricePerLiter.toStringAsFixed(2)} ₽/л',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: colors.text2,
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

class _Badge extends StatelessWidget {
  const _Badge({required this.label, required this.bg, required this.fg});

  final String label;
  final Color bg;
  final Color fg;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(left: 6),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(
        label,
        style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: fg),
      ),
    );
  }
}

class _ActionButton extends StatelessWidget {
  const _ActionButton({
    required this.label,
    required this.onTap,
    required this.color,
  });

  final String label;
  final VoidCallback onTap;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(
          border: Border.all(color: color.withValues(alpha: 0.5)),
          borderRadius: BorderRadius.circular(6),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w500,
            color: color,
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
    return ListView(
      children: [
        const SizedBox(height: 120),
        Center(child: Text(message, textAlign: TextAlign.center)),
        const SizedBox(height: 12),
        Center(
          child: OutlinedButton(
            onPressed: onRetry,
            child: const Text('Повторить'),
          ),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Create tariff bottom sheet (admin only)
// ---------------------------------------------------------------------------

class _CreateTariffSheet extends StatefulWidget {
  const _CreateTariffSheet({required this.onCreated});

  final VoidCallback onCreated;

  @override
  State<_CreateTariffSheet> createState() => _CreateTariffSheetState();
}

class _CreateTariffSheetState extends State<_CreateTariffSheet> {
  final _nameController = TextEditingController();
  final _descController = TextEditingController();
  final _deliveryController = TextEditingController(text: '0.00');
  bool _loading = false;
  String? _error;

  // Prices keyed by fuel type — same 5 fuels as web
  static const _fuels = [
    'DIESEL_SUMMER',
    'DIESEL_WINTER',
    'PETROL_92',
    'PETROL_95',
    'FUEL_OIL',
  ];

  final Map<String, TextEditingController> _priceControllers = {
    for (final f in _fuels) f: TextEditingController(),
  };

  @override
  void dispose() {
    _nameController.dispose();
    _descController.dispose();
    _deliveryController.dispose();
    for (final c in _priceControllers.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _submit() async {
    final name = _nameController.text.trim();
    if (name.isEmpty) {
      setState(() => _error = 'Укажите название тарифа');
      return;
    }

    final fuelPrices = <TariffFuelPrice>[];
    for (final fuel in _fuels) {
      final raw = _priceControllers[fuel]!.text.trim();
      if (raw.isEmpty) continue;
      final price = double.tryParse(raw);
      if (price == null || price <= 0) {
        setState(() => _error = 'Некорректная цена для ${FuelCatalog.label(fuel)}');
        return;
      }
      fuelPrices.add(TariffFuelPrice(id: '', fuelType: fuel, pricePerLiter: price));
    }
    if (fuelPrices.isEmpty) {
      setState(() => _error = 'Добавьте хотя бы одну цену на топливо');
      return;
    }

    final deliveryCost = double.tryParse(_deliveryController.text.trim()) ?? 0.0;

    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      await TariffsRepository.instance.create(
        TariffInput(
          name: name,
          description: _descController.text.trim().isEmpty
              ? null
              : _descController.text.trim(),
          fuelPrices: fuelPrices,
          baseDeliveryCost: deliveryCost,
        ),
      );
      if (!mounted) return;
      widget.onCreated();
    } on Exception catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = apiErrorMessage(e);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Padding(
      padding: EdgeInsets.only(
        left: 16,
        right: 16,
        top: 16,
        bottom: MediaQuery.viewInsetsOf(context).bottom + 16,
      ),
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                Text(
                  'Новый тариф',
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w700,
                    color: colors.text,
                  ),
                ),
                const Spacer(),
                IconButton(
                  icon: const Icon(Icons.close),
                  onPressed: () => Navigator.pop(context),
                ),
              ],
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _nameController,
              decoration: const InputDecoration(labelText: 'Название *'),
              textCapitalization: TextCapitalization.sentences,
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _descController,
              decoration: const InputDecoration(labelText: 'Описание'),
              textCapitalization: TextCapitalization.sentences,
            ),
            const SizedBox(height: 16),
            Text(
              'Цены за литр, ₽',
              style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: colors.text2,
              ),
            ),
            const SizedBox(height: 8),
            for (final fuel in _fuels) ...[
              Row(
                children: [
                  SizedBox(
                    width: 120,
                    child: Text(
                      FuelCatalog.label(fuel),
                      style: TextStyle(fontSize: 13, color: colors.text2),
                    ),
                  ),
                  Expanded(
                    child: TextField(
                      controller: _priceControllers[fuel],
                      keyboardType: const TextInputType.numberWithOptions(
                        decimal: true,
                      ),
                      decoration: const InputDecoration(
                        hintText: '0.00',
                        isDense: true,
                        contentPadding:
                            EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
            ],
            const SizedBox(height: 8),
            Row(
              children: [
                Text(
                  'Стоимость доставки, ₽/л',
                  style: TextStyle(fontSize: 13, color: colors.text2),
                ),
                const SizedBox(width: 12),
                SizedBox(
                  width: 90,
                  child: TextField(
                    controller: _deliveryController,
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                    ),
                    decoration: const InputDecoration(
                      isDense: true,
                      contentPadding:
                          EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                    ),
                  ),
                ),
              ],
            ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(
                _error!,
                style: TextStyle(fontSize: 13, color: colors.red),
              ),
            ],
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: _loading ? null : _submit,
                child: _loading
                    ? const SizedBox(
                        height: 18,
                        width: 18,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      )
                    : const Text('Создать тариф'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
