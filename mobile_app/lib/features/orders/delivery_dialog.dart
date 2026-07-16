import 'package:flutter/material.dart';

import '../inventory/inventory_repository.dart';

/// Результат диалога «Отметить доставку» (зеркало веб-модалки 2026-07-14):
/// фактический объём, комментарий в отчёт и — если заведены ёмкости —
/// ёмкость с новым показанием счётчика колонки.
class DeliveryInput {
  const DeliveryInput({
    required this.volume,
    this.comment,
    this.tankId,
    this.counterAfter,
  });

  final double volume;
  final String? comment;
  final String? tankId;
  final int? counterAfter;
}

/// Показывает диалог доставки. Возвращает null при отмене.
///
/// Ёмкости подгружаются заранее: если их нет (или сервис недоступен) —
/// блок ёмкости скрыт, как на вебе. Подходящие по виду топлива — первыми.
Future<DeliveryInput?> showDeliveryDialog(
  BuildContext context, {
  required double requestedVolume,
  required String fuelType,
}) async {
  List<Tank> tanks;
  try {
    tanks = (await InventoryRepository.instance.listTanks())
        .where((t) => t.isActive)
        .toList();
  } on Object {
    tanks = const []; // блок ёмкости останется скрыт
  }
  tanks.sort((a, b) => (b.fuelType == fuelType ? 1 : 0)
      .compareTo(a.fuelType == fuelType ? 1 : 0));
  if (!context.mounted) return null;

  final volumeCtrl = TextEditingController(
    text: requestedVolume > 0 ? requestedVolume.toStringAsFixed(0) : '',
  );
  final counterCtrl = TextEditingController();
  final commentCtrl = TextEditingController();
  String? tankId = tanks.isNotEmpty ? tanks.first.id : null;
  String? error;

  Tank? tankById(String? id) {
    for (final t in tanks) {
      if (t.id == id) return t;
    }
    return null;
  }

  // Литры по счётчику с переполнением шестизначного счётчика (999999 → 0).
  String counterHint() {
    final t = tankById(tankId);
    if (t == null) return '';
    final base = 'Текущее показание: ${t.counterText}';
    final afterRaw = counterCtrl.text.trim();
    if (afterRaw.isEmpty) return base;
    final after = int.tryParse(afterRaw);
    if (after == null || after < 0 || after > 999999) return base;
    final litres =
        after >= t.counter ? after - t.counter : 1000000 - t.counter + after;
    final vol =
        double.tryParse(volumeCtrl.text.trim().replaceAll(',', '.')) ?? 0;
    final mismatch = vol > 0 && (litres - vol).abs() > 0.5
        ? ' ⚠ не сходится с объёмом (${vol.toStringAsFixed(0)} л)'
        : '';
    return '$base · по счётчику: $litres л$mismatch';
  }

  final result = await showDialog<DeliveryInput>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setDialogState) => AlertDialog(
        title: const Text('Отметить доставку'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              TextField(
                controller: volumeCtrl,
                keyboardType:
                    const TextInputType.numberWithOptions(decimal: true),
                decoration: const InputDecoration(
                  labelText: 'Отгружено, литров *',
                  hintText: 'Фактический объём',
                  helperText: 'Сумма заявки будет пересчитана по '
                      'фактическому объёму. Номер ТТН присваивается '
                      'автоматически.',
                  helperMaxLines: 3,
                ),
                onChanged: (_) => setDialogState(() {}),
              ),
              if (tanks.isNotEmpty) ...[
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue: tankId,
                  isExpanded: true,
                  items: [
                    for (final t in tanks)
                      DropdownMenuItem(
                        value: t.id,
                        child: Text(
                          '${t.name} · ${t.fuelLabel ?? t.fuelType}'
                          '${t.fuelType != fuelType ? ' ⚠ другое топливо' : ''}'
                          ' · ${t.currentVolume.toStringAsFixed(0)} л',
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(fontSize: 13),
                        ),
                      ),
                  ],
                  onChanged: (v) => setDialogState(() => tankId = v),
                  decoration: const InputDecoration(
                      labelText: 'Из какой ёмкости *'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: counterCtrl,
                  keyboardType: TextInputType.number,
                  maxLength: 6,
                  decoration: InputDecoration(
                    labelText: 'Счётчик после отгрузки (6 цифр) *',
                    hintText: tankById(tankId)?.counterText ?? '230523',
                    counterText: '',
                    helperText: counterHint(),
                    helperMaxLines: 3,
                  ),
                  onChanged: (_) => setDialogState(() {}),
                ),
              ],
              const SizedBox(height: 12),
              TextField(
                controller: commentCtrl,
                maxLines: 2,
                decoration: const InputDecoration(
                  labelText: 'Комментарий (необязательно)',
                  hintText: 'Попадёт в отчёт: недолив, замечания '
                      'по адресу и т.п.',
                  alignLabelWithHint: true,
                ),
              ),
              if (error != null)
                Padding(
                  padding: const EdgeInsets.only(top: 10),
                  child: Text(
                    error!,
                    style: const TextStyle(color: Colors.red, fontSize: 13),
                  ),
                ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () {
              final vol = double.tryParse(
                  volumeCtrl.text.trim().replaceAll(',', '.'));
              if (vol == null || vol <= 0) {
                setDialogState(
                    () => error = 'Укажите отгруженный объём');
                return;
              }
              int? counterAfter;
              if (tanks.isNotEmpty) {
                if (tankId == null) {
                  setDialogState(() => error = 'Выберите ёмкость');
                  return;
                }
                counterAfter = int.tryParse(counterCtrl.text.trim());
                if (counterAfter == null ||
                    counterAfter < 0 ||
                    counterAfter > 999999) {
                  setDialogState(() => error =
                      'Введите показание счётчика (число до 6 цифр)');
                  return;
                }
              }
              final comment = commentCtrl.text.trim();
              Navigator.of(ctx).pop(DeliveryInput(
                volume: vol,
                comment: comment.isEmpty ? null : comment,
                tankId: tanks.isNotEmpty ? tankId : null,
                counterAfter: counterAfter,
              ));
            },
            child: const Text('ОК'),
          ),
        ],
      ),
    ),
  );
  return result;
}
