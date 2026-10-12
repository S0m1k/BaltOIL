import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import 'api_client.dart';
import 'app_config.dart';
import 'outbox_db.dart';

/// Синхронизирует офлайн-очередь водителя с бэкендом.
///
/// Конечный автомат каждой строки:
///   pending → (HTTP 2xx) → synced  (строка удаляется после flush)
///   pending → (4xx ≠ 409 + 422-конфликт) → conflict  (отставляется, очередь продолжается)
///   pending → (network error / 5xx) → pending  (повтор на следующем flush)
///
/// FIFO: строки обрабатываются в порядке id ASC. Конфликтная строка выставляется
/// aside (status = conflict) и НЕ блокирует последующие pending-строки.
class SyncService {
  SyncService._();
  static final SyncService instance = SyncService._();

  /// Подписчики изменений pending-счётчика — вызываются после каждого flush.
  final List<VoidCallback> _listeners = [];

  void addListener(VoidCallback cb) => _listeners.add(cb);
  void removeListener(VoidCallback cb) => _listeners.remove(cb);

  StreamSubscription<List<ConnectivityResult>>? _connectivitySub;
  bool _flushing = false;

  // --- конфликты, о которых нужно сообщить UI ---
  final List<OutboxEntry> _pendingConflicts = [];
  VoidCallback? onConflictsAvailable; // HomeScreen/DriverOrdersScreen ставит колбэк

  List<OutboxEntry> takeConflicts() {
    final copy = List<OutboxEntry>.from(_pendingConflicts);
    _pendingConflicts.clear();
    return copy;
  }

  /// Вызвать в main() один раз после запуска приложения.
  Future<void> init() async {
    // Слушаем изменения соединения.
    _connectivitySub = Connectivity()
        .onConnectivityChanged
        .listen((results) {
      final hasNetwork = results.any((r) => r != ConnectivityResult.none);
      if (hasNetwork) {
        flushNow();
      }
    });

    // Немедленная попытка при старте — если сеть есть, отошлём накопленное.
    flushNow();
  }

  void dispose() {
    _connectivitySub?.cancel();
  }

  /// Запустить flush прямо сейчас (вызывается также при постановке в очередь).
  Future<void> flushNow() async {
    if (_flushing) return; // один concurrent flush в любой момент
    _flushing = true;
    try {
      await _flush();
    } finally {
      _flushing = false;
    }
  }

  Future<void> _flush() async {
    final pending = await OutboxDb.instance.listPending();
    if (pending.isEmpty) return;

    bool anyChange = false;

    for (final entry in pending) {
      final result = await _sendEntry(entry);
      if (result == _SendResult.synced) {
        await OutboxDb.instance.markSynced(entry.id);
        anyChange = true;
      } else if (result == _SendResult.conflict) {
        // конфликт — отставляем, продолжаем следующую строку
        anyChange = true;
      }
      // network/5xx — оставляем pending, не меняем
    }

    if (anyChange) {
      await OutboxDb.instance.deleteSynced();
      // подтянуть накопившиеся конфликты и сообщить UI
      final conflicts = await OutboxDb.instance.listConflicts();
      if (conflicts.isNotEmpty) {
        _pendingConflicts.addAll(conflicts);
        onConflictsAvailable?.call();
      }
      _notifyListeners();
    }
  }

  Future<_SendResult> _sendEntry(OutboxEntry entry) async {
    try {
      final dio = ApiClient.instance.dio;
      final base = AppConfig.orderBase;

      switch (entry.operation) {
        case 'transition':
          await dio.post(
            '$base/orders/${entry.orderId}/transition',
            data: {
              ...entry.payload,
              'idempotency_key': entry.idempotencyKey,
            },
            options: Options(receiveTimeout: const Duration(seconds: 60)),
          );
        case 'ack_changes':
          await dio.post(
            '$base/orders/${entry.orderId}/ack-changes',
            data: {
              ...entry.payload,
              'idempotency_key': entry.idempotencyKey,
            },
          );
        case 'payment_record':
          await dio.post(
            '$base/payments/record',
            data: {
              ...entry.payload,
              'idempotency_key': entry.idempotencyKey,
            },
          );
        default:
          // Неизвестная операция — конфликт, чтобы не зависнуть.
          await OutboxDb.instance.markConflict(
              entry.id, 'unknown operation: ${entry.operation}');
          return _SendResult.conflict;
      }

      return _SendResult.synced;
    } on DioException catch (e) {
      final status = e.response?.statusCode;
      if (status != null && status >= 400 && status < 500) {
        // 4xx — действие отвергнуто бэком (неверный переход, уже отменена и т.д.)
        // LWW: офлайн-действие проигрывает, помечаем conflict.
        final msg = _extractDetail(e) ??
            'HTTP $status: действие отклонено сервером';
        await OutboxDb.instance.markConflict(entry.id, msg);
        return _SendResult.conflict;
      }
      // network / 5xx — повтор позже
      return _SendResult.retry;
    } catch (e) {
      // Непредвиденное — повтор
      return _SendResult.retry;
    }
  }

  String? _extractDetail(DioException e) {
    final data = e.response?.data;
    if (data is Map && data['detail'] != null) {
      final detail = data['detail'];
      if (detail is String) return detail;
    }
    return null;
  }

  void _notifyListeners() {
    for (final cb in List.of(_listeners)) {
      cb();
    }
  }
}

enum _SendResult { synced, conflict, retry }
