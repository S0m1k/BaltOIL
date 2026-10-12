import 'dart:convert';

import 'package:sqflite/sqflite.dart';
import 'package:path/path.dart' as p;

/// Одна строка очереди.
class OutboxEntry {
  OutboxEntry({
    required this.id,
    required this.idempotencyKey,
    required this.operation,
    required this.orderId,
    required this.payload,
    required this.clientTs,
    required this.status,
    this.error,
    required this.createdAt,
  });

  final int id;
  final String idempotencyKey; // UUID, стабилен по всем повторным попыткам
  final String operation; // transition | ack_changes | payment_record
  final String orderId;
  final Map<String, dynamic> payload; // тело запроса без idempotency_key
  final DateTime clientTs; // момент, когда водитель нажал кнопку
  final String status; // pending | synced | conflict
  final String? error;
  final DateTime createdAt;

  OutboxEntry copyWith({String? status, String? error}) => OutboxEntry(
        id: id,
        idempotencyKey: idempotencyKey,
        operation: operation,
        orderId: orderId,
        payload: payload,
        clientTs: clientTs,
        status: status ?? this.status,
        error: error ?? this.error,
        createdAt: createdAt,
      );

  Map<String, dynamic> toDbRow() => {
        'idempotency_key': idempotencyKey,
        'operation': operation,
        'order_id': orderId,
        'payload': jsonEncode(payload),
        'client_ts': clientTs.toIso8601String(),
        'status': status,
        'error': error,
        'created_at': createdAt.toIso8601String(),
      };

  factory OutboxEntry.fromDbRow(Map<String, dynamic> row) => OutboxEntry(
        id: row['id'] as int,
        idempotencyKey: row['idempotency_key'] as String,
        operation: row['operation'] as String,
        orderId: row['order_id'] as String,
        payload:
            jsonDecode(row['payload'] as String) as Map<String, dynamic>,
        clientTs: DateTime.parse(row['client_ts'] as String),
        status: row['status'] as String,
        error: row['error'] as String?,
        createdAt: DateTime.parse(row['created_at'] as String),
      );
}

/// SQLite-хранилище офлайн-очереди.
///
/// Singleton; инициализируется один раз, все методы thread-safe через sqflite.
class OutboxDb {
  OutboxDb._();
  static final OutboxDb instance = OutboxDb._();

  Database? _db;

  Future<Database> _open() async {
    if (_db != null) return _db!;
    final dbPath = await getDatabasesPath();
    _db = await openDatabase(
      p.join(dbPath, 'outbox.db'),
      version: 1,
      onCreate: (db, version) => db.execute('''
        CREATE TABLE outbox (
          id              INTEGER PRIMARY KEY AUTOINCREMENT,
          idempotency_key TEXT    NOT NULL UNIQUE,
          operation       TEXT    NOT NULL,
          order_id        TEXT    NOT NULL,
          payload         TEXT    NOT NULL,
          client_ts       TEXT    NOT NULL,
          status          TEXT    NOT NULL DEFAULT 'pending',
          error           TEXT,
          created_at      TEXT    NOT NULL
        )
      '''),
    );
    return _db!;
  }

  /// Добавить действие в очередь.
  /// id-строки возвращается через listPending (там row['id'] уже есть).
  Future<void> enqueue(OutboxEntry entry) async {
    final db = await _open();
    await db.insert('outbox', entry.toDbRow(),
        conflictAlgorithm: ConflictAlgorithm.ignore);
    // ConflictAlgorithm.ignore: если idempotency_key уже есть (двойной тап),
    // повторная вставка молча игнорируется.
  }

  /// Все строки со status = 'pending', в порядке FIFO (id ASC).
  Future<List<OutboxEntry>> listPending() async {
    final db = await _open();
    final rows = await db.query('outbox',
        where: "status = 'pending'", orderBy: 'id ASC');
    return rows.map(OutboxEntry.fromDbRow).toList();
  }

  /// Количество pending-строк для конкретной заявки (для бейджа на карточке).
  Future<int> pendingCountForOrder(String orderId) async {
    final db = await _open();
    final rows = await db.query(
      'outbox',
      columns: ['COUNT(*) as c'],
      where: "order_id = ? AND status = 'pending'",
      whereArgs: [orderId],
    );
    return (rows.first['c'] as int?) ?? 0;
  }

  /// Количество всех pending-строк (для глобального индикатора).
  Future<int> totalPending() async {
    final db = await _open();
    final rows = await db.query(
      'outbox',
      columns: ['COUNT(*) as c'],
      where: "status = 'pending'",
    );
    return (rows.first['c'] as int?) ?? 0;
  }

  Future<void> markSynced(int id) async {
    final db = await _open();
    await db.update(
      'outbox',
      {'status': 'synced'},
      where: 'id = ?',
      whereArgs: [id],
    );
  }

  Future<void> markConflict(int id, String error) async {
    final db = await _open();
    await db.update(
      'outbox',
      {'status': 'conflict', 'error': error},
      where: 'id = ?',
      whereArgs: [id],
    );
  }

  /// Удалить все синхронизированные строки (после успешного flush).
  Future<void> deleteSynced() async {
    final db = await _open();
    await db.delete('outbox', where: "status = 'synced'");
  }

  /// Все конфликтные строки — для показа водителю.
  Future<List<OutboxEntry>> listConflicts() async {
    final db = await _open();
    final rows = await db.query('outbox',
        where: "status = 'conflict'", orderBy: 'id ASC');
    return rows.map(OutboxEntry.fromDbRow).toList();
  }

  /// Удалить конкретную конфликтную строку (водитель ознакомился).
  Future<void> deleteEntry(int id) async {
    final db = await _open();
    await db.delete('outbox', where: 'id = ?', whereArgs: [id]);
  }
}
