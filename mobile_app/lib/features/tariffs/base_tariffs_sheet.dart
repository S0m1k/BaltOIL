import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/theme.dart';
import '../orders/order_models.dart';
import 'tariffs_repository.dart';

/// Модал «Базовые тарифы» (веб showBaseTariffsModal, 2026-07-10):
/// таблица цен физлицо / юрлицо (с НДС) + базовая доставка.
/// Доступен водителям, менеджерам и админам.
Future<void> showBaseTariffsSheet(BuildContext context) {
  return showModalBottomSheet<void>(
    context: context,
    showDragHandle: true,
    isScrollControlled: true,
    builder: (_) => const _BaseTariffsSheet(),
  );
}

/// Метка топлива без учёта регистра: тарифы хранят коды в верхнем
/// регистре (DIESEL_SUMMER), каталог — в нижнем (веб-фикс 80e0aa6).
String _fuelLabel(String code) {
  final label = FuelCatalog.label(code);
  if (label != code) return label;
  return FuelCatalog.label(code.toLowerCase());
}

class _BaseTariffsSheet extends StatelessWidget {
  const _BaseTariffsSheet();

  String _price(Tariff? t, String code) {
    final fp = t?.fuelPrices
        .where((p) => p.fuelType.toLowerCase() == code.toLowerCase())
        .firstOrNull;
    return fp != null ? '${fp.pricePerLiter.toStringAsFixed(2)} ₽/л' : '—';
  }

  String _delivery(Tariff? t) =>
      t != null ? '${t.baseDeliveryCost.toStringAsFixed(0)} ₽' : '—';

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return SafeArea(
      child: FutureBuilder<List<Tariff>>(
        future: TariffsRepository.instance.defaults(),
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const SizedBox(
              height: 220,
              child: Center(child: CircularProgressIndicator()),
            );
          }
          if (snap.hasError) {
            return SizedBox(
              height: 220,
              child: Center(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Text(apiErrorMessage(snap.error!),
                      textAlign: TextAlign.center),
                ),
              ),
            );
          }
          final tariffs = snap.data ?? const <Tariff>[];
          final ind = tariffs
                  .where((t) => t.clientType == 'individual')
                  .firstOrNull ??
              tariffs.where((t) => t.clientType == null).firstOrNull;
          final com =
              tariffs.where((t) => t.clientType == 'company').firstOrNull ??
                  tariffs.where((t) => t.clientType == null).firstOrNull;
          if (ind == null && com == null) {
            return const SizedBox(
              height: 180,
              child: Center(child: Text('Базовые тарифы не настроены')),
            );
          }
          // Все виды топлива, встречающиеся в обоих тарифах.
          final codes = <String>{
            ...?ind?.fuelPrices.map((p) => p.fuelType),
            ...?com?.fuelPrices.map((p) => p.fuelType),
          }.toList();
          return SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Базовые тарифы',
                    style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 12),
                Table(
                  columnWidths: const {
                    0: FlexColumnWidth(1.2),
                    1: FlexColumnWidth(1),
                    2: FlexColumnWidth(1),
                  },
                  children: [
                    TableRow(
                      decoration: BoxDecoration(
                        border: Border(
                            bottom: BorderSide(color: colors.border)),
                      ),
                      children: [
                        _HeadCell('Топливо', colors),
                        _HeadCell('Физлицо', colors, right: true),
                        _HeadCell('Юрлицо (с НДС)', colors, right: true),
                      ],
                    ),
                    for (final code in codes)
                      TableRow(
                        decoration: BoxDecoration(
                          border: Border(
                              bottom: BorderSide(color: colors.border)),
                        ),
                        children: [
                          _Cell(_fuelLabel(code), colors),
                          _Cell(_price(ind, code), colors,
                              right: true, mono: true),
                          _Cell(_price(com, code), colors,
                              right: true, mono: true),
                        ],
                      ),
                  ],
                ),
                const SizedBox(height: 12),
                Text(
                  'Цена для физлица — по столбцу «Физлицо» + доставка '
                  '(база ${_delivery(ind)})\n'
                  'Цена для юрлица — по столбцу «Юрлицо (с НДС)» + доставка '
                  '(база ${_delivery(com)})',
                  style: TextStyle(fontSize: 12, color: colors.text2),
                ),
                const SizedBox(height: 4),
                Text(
                  'Стоимость доставки умножается на коэффициент зоны доставки.',
                  style: TextStyle(fontSize: 12, color: colors.text3),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _HeadCell extends StatelessWidget {
  const _HeadCell(this.text, this.colors, {this.right = false});

  final String text;
  final AppColors colors;
  final bool right;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 6),
      child: Text(
        text,
        textAlign: right ? TextAlign.right : TextAlign.left,
        style: TextStyle(fontSize: 12, color: colors.text3),
      ),
    );
  }
}

class _Cell extends StatelessWidget {
  const _Cell(this.text, this.colors, {this.right = false, this.mono = false});

  final String text;
  final AppColors colors;
  final bool right;
  final bool mono;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 6),
      child: Text(
        text,
        textAlign: right ? TextAlign.right : TextAlign.left,
        style: TextStyle(
          fontSize: 12,
          color: colors.text,
          fontFamily: mono ? 'monospace' : null,
        ),
      ),
    );
  }
}
