import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../auth/auth_repository.dart';
import 'vehicles_repository.dart';

/// Транспортные средства (веб pane-vehicles): staff видит все и управляет,
/// водитель — просмотр. Клиенту раздел не показывается.
class VehiclesScreen extends StatefulWidget {
  const VehiclesScreen({super.key, required this.user});

  final CurrentUser user;

  @override
  State<VehiclesScreen> createState() => _VehiclesScreenState();
}

class _VehiclesScreenState extends State<VehiclesScreen> {
  late Future<List<Vehicle>> _future;

  bool get _isStaff =>
      widget.user.role == 'admin' || widget.user.role == 'manager';

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    setState(() {
      _future = VehiclesRepository.instance.list();
    });
  }

  Future<void> _addVehicle() async {
    final plate = TextEditingController();
    final model = TextEditingController();
    final cap = TextEditingController();
    final notes = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Новое транспортное средство'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: plate,
                autofocus: true,
                decoration: const InputDecoration(
                    labelText: 'Госномер', hintText: 'А123ВС78'),
              ),
              TextField(
                controller: model,
                decoration: const InputDecoration(
                    labelText: 'Модель / Марка', hintText: 'КАМАЗ-5320'),
              ),
              TextField(
                controller: cap,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                    labelText: 'Объём цистерны (л)', hintText: '10000'),
              ),
              TextField(
                controller: notes,
                decoration: const InputDecoration(labelText: 'Примечания'),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Отмена')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Создать')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    final capVal = double.tryParse(cap.text.replaceAll(',', '.'));
    if (plate.text.trim().isEmpty || model.text.trim().isEmpty ||
        capVal == null) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Заполните госномер, модель и объём')));
      return;
    }
    try {
      await VehiclesRepository.instance.create(
        plateNumber: plate.text.trim(),
        model: model.text.trim(),
        capacityLiters: capVal,
        notes: notes.text.trim(),
      );
      _load();
    } on Object catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
  }

  Future<void> _archive(Vehicle v) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Архивировать ТС?'),
        content: Text('${v.plateNumber} — ${v.model}'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Отмена')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('В архив')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    try {
      await VehiclesRepository.instance.archive(v.id);
      _load();
    } on Object catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      floatingActionButton: _isStaff
          ? FloatingActionButton.extended(
              onPressed: _addVehicle,
              icon: const Icon(Icons.add),
              label: const Text('Добавить ТС'),
            )
          : null,
      body: RefreshIndicator(
        onRefresh: () async => _load(),
        child: FutureBuilder<List<Vehicle>>(
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
            final vehicles = snap.data ?? const [];
            if (vehicles.isEmpty) {
              return ListView(children: const [
                SizedBox(height: 120),
                Center(child: Text('Транспортных средств нет')),
              ]);
            }
            return ListView.builder(
              padding: const EdgeInsets.all(12),
              itemCount: vehicles.length,
              itemBuilder: (context, i) => _VehicleCard(
                vehicle: vehicles[i],
                isStaff: _isStaff,
                onArchive: () => _archive(vehicles[i]),
              ),
            );
          },
        ),
      ),
    );
  }
}

class _VehicleCard extends StatelessWidget {
  const _VehicleCard({
    required this.vehicle,
    required this.isStaff,
    required this.onArchive,
  });

  final Vehicle vehicle;
  final bool isStaff;
  final VoidCallback onArchive;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final muted = theme.textTheme.bodySmall
        ?.copyWith(color: theme.colorScheme.onSurfaceVariant);
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(vehicle.plateNumber,
                      style: const TextStyle(
                          fontWeight: FontWeight.w700, fontSize: 16)),
                ),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: (vehicle.isActive ? Colors.teal : Colors.grey)
                        .withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text(
                    vehicle.isActive ? 'Активно' : 'Неактивно',
                    style: TextStyle(
                        fontSize: 12,
                        color:
                            vehicle.isActive ? Colors.teal : Colors.grey),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 2),
            Text(vehicle.model, style: muted),
            const SizedBox(height: 4),
            Text(
              [
                '${vehicle.capacityLiters.toStringAsFixed(0)} л',
                vehicle.assignedDriverId == null
                    ? 'Свободно'
                    : 'Водитель назначен',
              ].join(' · '),
              style: muted,
            ),
            if (vehicle.notes != null && vehicle.notes!.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(vehicle.notes!, style: muted),
              ),
            if (isStaff)
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                  onPressed: onArchive,
                  child: const Text('Архив',
                      style: TextStyle(color: Colors.red)),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
