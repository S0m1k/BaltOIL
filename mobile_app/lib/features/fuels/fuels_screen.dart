import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../orders/order_models.dart';
import '../orders/orders_repository.dart';

/// Справочник топлива (веб pane-fuels): карточки код/название/зимнее.
/// Виден всем ролям, только просмотр.
class FuelsScreen extends StatefulWidget {
  const FuelsScreen({super.key});

  @override
  State<FuelsScreen> createState() => _FuelsScreenState();
}

class _FuelsScreenState extends State<FuelsScreen> {
  late Future<List<FuelType>> _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    setState(() {
      _future = OrdersRepository.instance.fuelTypes();
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return RefreshIndicator(
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
              childAspectRatio: 1.6,
            ),
            itemCount: fuels.length,
            itemBuilder: (context, i) {
              final f = fuels[i];
              return Card(
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text(f.code,
                          style: theme.textTheme.titleMedium
                              ?.copyWith(fontWeight: FontWeight.w700)),
                      const SizedBox(height: 4),
                      Text(f.label,
                          style: theme.textTheme.bodySmall,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis),
                      if (f.isWinter)
                        Padding(
                          padding: const EdgeInsets.only(top: 4),
                          child: Text('зимнее',
                              style: theme.textTheme.bodySmall?.copyWith(
                                  color: theme.colorScheme.primary)),
                        ),
                    ],
                  ),
                ),
              );
            },
          );
        },
      ),
    );
  }
}
