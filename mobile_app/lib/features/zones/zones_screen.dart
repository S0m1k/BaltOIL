import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/theme.dart';
import '../auth/auth_repository.dart';
import 'zones_repository.dart';

// ---------------------------------------------------------------------------
// Screen
// ---------------------------------------------------------------------------

class ZonesScreen extends StatefulWidget {
  const ZonesScreen({super.key, required this.user});

  final CurrentUser user;

  @override
  State<ZonesScreen> createState() => _ZonesScreenState();
}

class _ZonesScreenState extends State<ZonesScreen> {
  late Future<List<DeliveryZone>> _future;

  bool get _isAdmin => widget.user.role == 'admin';

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    _future = ZonesRepository.instance.listActive();
  }

  Future<void> _reload() async {
    final f = ZonesRepository.instance.listActive();
    setState(() => _future = f);
    await f;
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

  Future<void> _showCreateDialog() async {
    final result = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (ctx) =>
          _CreateZoneSheet(onCreated: () => Navigator.pop(ctx, true)),
    );
    if (result == true) await _reload();
  }

  Future<void> _editPrice(DeliveryZone zone) async {
    final result = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (ctx) => _EditPriceSheet(
        zone: zone,
        onSaved: () => Navigator.pop(ctx, true),
      ),
    );
    if (result == true) await _reload();
  }

  Future<void> _delete(DeliveryZone zone) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Удалить зону?'),
        content: Text(
          '«${zone.name}» будет удалена. Действие необратимо.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Отмена'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(
              'Удалить',
              style: TextStyle(color: context.colors.red),
            ),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await ZonesRepository.instance.delete(zone.id);
      if (!mounted) return;
      _showSnack('Зона «${zone.name}» удалена');
      await _reload();
    } on Exception catch (e) {
      if (!mounted) return;
      _showSnack(apiErrorMessage(e), isError: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Column(
      children: [
        // Toolbar
        Container(
          color: colors.bg,
          padding:
              const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          child: Row(
            children: [
              Text(
                'Зоны доставки',
                style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: colors.text,
                ),
              ),
              const Spacer(),
              if (_isAdmin)
                FilledButton.icon(
                  onPressed: _showCreateDialog,
                  icon: const Icon(Icons.add, size: 16),
                  label: const Text('Новая зона'),
                  style: FilledButton.styleFrom(
                    visualDensity: VisualDensity.compact,
                    padding: const EdgeInsets.symmetric(
                        horizontal: 12, vertical: 6),
                  ),
                ),
            ],
          ),
        ),
        Divider(height: 1, color: colors.border),
        // List
        Expanded(
          child: RefreshIndicator(
            onRefresh: _reload,
            child: FutureBuilder<List<DeliveryZone>>(
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
                final zones = snap.data ?? const [];
                if (zones.isEmpty) {
                  return ListView(
                    children: const [
                      SizedBox(height: 120),
                      Center(
                        child: Text(
                          'Зон доставки пока нет',
                          textAlign: TextAlign.center,
                        ),
                      ),
                    ],
                  );
                }
                return ListView.separated(
                  padding: const EdgeInsets.all(12),
                  itemCount: zones.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 10),
                  itemBuilder: (context, i) => _ZoneCard(
                    zone: zones[i],
                    isAdmin: _isAdmin,
                    onEditPrice: () => _editPrice(zones[i]),
                    onDelete: () => _delete(zones[i]),
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
// Zone card
// ---------------------------------------------------------------------------

class _ZoneCard extends StatelessWidget {
  const _ZoneCard({
    required this.zone,
    required this.isAdmin,
    required this.onEditPrice,
    required this.onDelete,
  });

  final DeliveryZone zone;
  final bool isAdmin;
  final VoidCallback onEditPrice;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final hasPrice = zone.deliveryPrice != null;
    final priceLabel = hasPrice
        ? '${zone.deliveryPrice!.toStringAsFixed(2)} ₽'
        : 'по коэффициенту ×${zone.costCoefficient.toStringAsFixed(2)}';
    final pointCount = zone.polygon.length;

    return Container(
      decoration: BoxDecoration(
        color: colors.bg2,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: colors.border),
      ),
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header: name + active badge
          Row(
            children: [
              Expanded(
                child: Text(
                  zone.name,
                  style: TextStyle(
                    fontWeight: FontWeight.w600,
                    fontSize: 15,
                    color: colors.text,
                  ),
                ),
              ),
              if (!zone.isActive)
                _Badge(
                  label: 'Неактивна',
                  bg: colors.bg3,
                  fg: colors.text3,
                ),
            ],
          ),
          const SizedBox(height: 8),
          // Delivery price row
          Row(
            children: [
              Icon(Icons.local_shipping_outlined,
                  size: 14, color: colors.text3),
              const SizedBox(width: 6),
              Text(
                'Доставка: $priceLabel',
                style: TextStyle(fontSize: 13, color: colors.text2),
              ),
            ],
          ),
          const SizedBox(height: 4),
          // Polygon point count
          Row(
            children: [
              Icon(Icons.place_outlined, size: 14, color: colors.text3),
              const SizedBox(width: 6),
              Text(
                pointCount > 0
                    ? 'Полигон: $pointCount точек'
                    : 'Полигон не задан',
                style: TextStyle(fontSize: 12, color: colors.text3),
              ),
            ],
          ),
          // Admin actions
          if (isAdmin) ...[
            const SizedBox(height: 12),
            Row(
              children: [
                _ActionButton(
                  label: 'Изменить цену',
                  onTap: onEditPrice,
                  color: colors.primary,
                ),
                const SizedBox(width: 8),
                _ActionButton(
                  label: 'Удалить',
                  onTap: onDelete,
                  color: colors.red,
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Create zone bottom sheet (admin only)
// ---------------------------------------------------------------------------

class _CreateZoneSheet extends StatefulWidget {
  const _CreateZoneSheet({required this.onCreated});

  final VoidCallback onCreated;

  @override
  State<_CreateZoneSheet> createState() => _CreateZoneSheetState();
}

class _CreateZoneSheetState extends State<_CreateZoneSheet> {
  final _nameController = TextEditingController();
  final _priceController = TextEditingController();
  bool _loading = false;
  String? _error;

  @override
  void dispose() {
    _nameController.dispose();
    _priceController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final name = _nameController.text.trim();
    if (name.isEmpty) {
      setState(() => _error = 'Укажите название зоны');
      return;
    }
    final priceRaw = _priceController.text.trim();
    final price = double.tryParse(priceRaw);
    if (price == null || price < 0) {
      setState(() => _error = 'Укажите корректную стоимость доставки (₽)');
      return;
    }

    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      await ZonesRepository.instance.create(
        ZoneCreateInput(name: name, deliveryPrice: price),
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
                  'Новая зона доставки',
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
            const SizedBox(height: 4),
            Text(
              'Полигон зоны задаётся через веб-интерфейс.',
              style: TextStyle(fontSize: 12, color: colors.text3),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _nameController,
              decoration: const InputDecoration(labelText: 'Название *'),
              textCapitalization: TextCapitalization.sentences,
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _priceController,
              decoration: const InputDecoration(
                labelText: 'Стоимость доставки, ₽ *',
                hintText: '0.00',
              ),
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
            ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(
                _error!,
                style: TextStyle(fontSize: 13, color: colors.red),
              ),
            ],
            const SizedBox(height: 20),
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
                    : const Text('Создать зону'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Edit price bottom sheet (admin only)
// ---------------------------------------------------------------------------

class _EditPriceSheet extends StatefulWidget {
  const _EditPriceSheet({required this.zone, required this.onSaved});

  final DeliveryZone zone;
  final VoidCallback onSaved;

  @override
  State<_EditPriceSheet> createState() => _EditPriceSheetState();
}

class _EditPriceSheetState extends State<_EditPriceSheet> {
  late final TextEditingController _priceController;
  bool _loading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _priceController = TextEditingController(
      text: widget.zone.deliveryPrice?.toStringAsFixed(2) ?? '',
    );
  }

  @override
  void dispose() {
    _priceController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final priceRaw = _priceController.text.trim();
    final price = double.tryParse(priceRaw);
    if (price == null || price < 0) {
      setState(() => _error = 'Укажите корректную стоимость (₽)');
      return;
    }

    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      await ZonesRepository.instance.update(
        widget.zone.id,
        ZoneUpdateInput(deliveryPrice: price),
      );
      if (!mounted) return;
      widget.onSaved();
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
                Expanded(
                  child: Text(
                    'Изменить цену: ${widget.zone.name}',
                    style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.w700,
                      color: colors.text,
                    ),
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.close),
                  onPressed: () => Navigator.pop(context),
                ),
              ],
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _priceController,
              autofocus: true,
              decoration: const InputDecoration(
                labelText: 'Стоимость доставки, ₽',
                hintText: '0.00',
              ),
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
            ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(
                _error!,
                style: TextStyle(fontSize: 13, color: colors.red),
              ),
            ],
            const SizedBox(height: 20),
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
                    : const Text('Сохранить'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Helpers
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
