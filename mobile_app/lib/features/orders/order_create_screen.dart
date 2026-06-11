import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import 'order_models.dart';
import 'orders_repository.dart';

class OrderCreateScreen extends StatefulWidget {
  const OrderCreateScreen({super.key});

  @override
  State<OrderCreateScreen> createState() => _OrderCreateScreenState();
}

class _OrderCreateScreenState extends State<OrderCreateScreen> {
  final _formKey = GlobalKey<FormState>();
  final _volume = TextEditingController();
  final _address = TextEditingController();
  final _comment = TextEditingController();

  List<FuelType>? _fuelTypes;
  String? _fuelCode;
  DateTime? _desiredDate;
  String _paymentType = 'on_delivery'; // как на вебе: «По факту» по умолчанию
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadFuelTypes();
  }

  Future<void> _loadFuelTypes() async {
    try {
      final types = await OrdersRepository.instance.fuelTypes();
      setState(() {
        _fuelTypes = types;
        if (types.isNotEmpty) _fuelCode = types.first.code;
      });
    } catch (e) {
      setState(() => _error = apiErrorMessage(e));
    }
  }

  Future<void> _pickDate() async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: now.add(const Duration(days: 1)),
      firstDate: now,
      lastDate: now.add(const Duration(days: 60)),
    );
    if (picked != null) setState(() => _desiredDate = picked);
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate() || _fuelCode == null) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await OrdersRepository.instance.create(
        fuelType: _fuelCode!,
        volume: double.parse(_volume.text.replaceAll(',', '.')),
        address: _address.text.trim(),
        paymentType: _paymentType,
        desiredDate: _desiredDate,
        comment: _comment.text.trim(),
      );
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      setState(() => _error = apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final types = _fuelTypes;
    return Scaffold(
      appBar: AppBar(title: const Text('Новая заявка на топливо')),
      body: types == null
          ? Center(
              child: _error == null
                  ? const CircularProgressIndicator()
                  : Text(_error!))
          : Form(
              key: _formKey,
              child: ListView(
                padding: const EdgeInsets.all(24),
                children: [
                  DropdownButtonFormField<String>(
                    initialValue: _fuelCode,
                    items: [
                      for (final t in types)
                        DropdownMenuItem(value: t.code, child: Text(t.label)),
                    ],
                    onChanged: (v) => setState(() => _fuelCode = v),
                    decoration: const InputDecoration(
                      labelText: 'Вид топлива',
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: _volume,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: 'Объём (литры, min 300)',
                      border: OutlineInputBorder(),
                    ),
                    validator: (v) {
                      final n = double.tryParse((v ?? '').replaceAll(',', '.'));
                      if (n == null) return 'Укажите объём';
                      if (n < 300) return 'Минимальный объём — 300 литров';
                      return null;
                    },
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: _address,
                    decoration: const InputDecoration(
                      labelText: 'Адрес доставки',
                      border: OutlineInputBorder(),
                    ),
                    validator: (v) =>
                        (v == null || v.trim().length < 5) ? 'Укажите адрес' : null,
                  ),
                  const SizedBox(height: 16),
                  OutlinedButton.icon(
                    onPressed: _pickDate,
                    icon: const Icon(Icons.calendar_today, size: 18),
                    label: Text(_desiredDate == null
                        ? 'Желаемая дата доставки'
                        : 'Дата: ${_desiredDate!.day}.${_desiredDate!.month}.${_desiredDate!.year}'),
                  ),
                  const SizedBox(height: 16),
                  Text('Тип оплаты',
                      style: Theme.of(context).textTheme.bodySmall),
                  RadioGroup<String>(
                    groupValue: _paymentType,
                    onChanged: (v) =>
                        setState(() => _paymentType = v ?? 'on_delivery'),
                    child: const Column(
                      children: [
                        RadioListTile<String>(
                          value: 'on_delivery',
                          dense: true,
                          title: Text('По факту (при прибытии)'),
                        ),
                        RadioListTile<String>(
                          value: 'prepaid',
                          dense: true,
                          title: Text('Предоплата'),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 8),
                  TextFormField(
                    controller: _comment,
                    maxLines: 2,
                    decoration: const InputDecoration(
                      labelText: 'Комментарий',
                      hintText: 'Дополнительные пожелания...',
                      border: OutlineInputBorder(),
                    ),
                  ),
                  if (_error != null) ...[
                    const SizedBox(height: 12),
                    Text(_error!, style: const TextStyle(color: Colors.red)),
                  ],
                  const SizedBox(height: 24),
                  FilledButton(
                    onPressed: _busy ? null : _submit,
                    child: _busy
                        ? const SizedBox(
                            height: 20,
                            width: 20,
                            child: CircularProgressIndicator(strokeWidth: 2))
                        : const Text('Отправить заявку'),
                  ),
                ],
              ),
            ),
    );
  }
}
