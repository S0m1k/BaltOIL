import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_callkit_incoming/flutter_callkit_incoming.dart';

import 'call_repository.dart';
import 'call_screen.dart';

/// Поллинг входящих звонков (веб startCallPolling, раз в ~3 с):
/// GET /calls/active → первый RINGING, где мы не инициатор, показывается
/// диалогом «Принять / Отклонить». Если звонок пропал из active (инициатор
/// отбил) — диалог снимается, не дожидаясь таймаута.
class IncomingCallWatcher {
  IncomingCallWatcher._();
  static final IncomingCallWatcher instance = IncomingCallWatcher._();

  GlobalKey<NavigatorState>? navigatorKey;

  Timer? _timer;
  String? _userId;

  /// id звонка, диалог которого сейчас на экране (null — не показан).
  String? _incomingCallId;
  bool _inCall = false;

  void start({required String userId}) {
    _userId = userId;
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 4), (_) => _poll());
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
    _userId = null;
  }

  /// Немедленный тик — дёргается из пуша call_initiated (форграунд),
  /// чтобы диалог входящего появился сразу, а не через интервал поллинга.
  Future<void> pollNow() => _poll();

  /// Открыть входящий звонок по id — тап по пушу call_initiated
  /// (приложение было в фоне или убито). Если звонок ещё звонит —
  /// показываем стандартный диалог «Принять / Отклонить».
  Future<void> openFromPush(String callId) async {
    if (_inCall || _incomingCallId != null) return;
    final nav = navigatorKey?.currentState;
    if (nav == null) return;
    try {
      final call = await CallRepository.instance.getCall(callId);
      if (call.status != 'ringing') return; // уже отвечен/завершён
      await _showIncoming(nav, call);
    } on Object {
      // Звонок мог истечь, пока приложение запускалось.
    }
  }

  Future<void> _poll() async {
    if (_inCall || _userId == null) return;
    List<CallInfo> list;
    try {
      list = await CallRepository.instance.active();
    } on Object {
      return; // сервис может быть недоступен — молча пропускаем тик
    }
    final nav = navigatorKey?.currentState;
    if (nav == null) return;

    // Показанный входящий пропал из active → инициатор отбил, снимаем диалог.
    if (_incomingCallId != null) {
      final still = list.any(
          (c) => c.id == _incomingCallId && c.status == 'ringing');
      if (!still) {
        _incomingCallId = null;
        nav.pop();
      }
      return;
    }

    // Если нативный экран звонка (callkit) уже показывает входящий — не дублируем
    // in-app диалогом. Поллер здесь только страховка на случай непришедшего пуша.
    Set<String> callkitIds = const {};
    try {
      final active = await FlutterCallkitIncoming.activeCalls();
      callkitIds = {
        for (final c in active)
          if ((c.extra?['call_id'] ?? c.id) != null)
            (c.extra?['call_id'] ?? c.id).toString(),
      };
    } on Object {
      // Плагин мог быть недоступен — игнорируем, покажем обычный диалог.
    }

    for (final c in list) {
      if (c.status != 'ringing') continue;
      if (c.initiatedById == _userId) continue;
      if (callkitIds.contains(c.id)) continue; // уже показывает callkit
      _showIncoming(nav, c);
      break;
    }
  }

  Future<void> _showIncoming(NavigatorState nav, CallInfo call) async {
    _incomingCallId = call.id;
    final accepted = await showDialog<bool>(
      context: nav.context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        icon: const Icon(Icons.phone_in_talk, size: 36),
        title: Text('${call.initiatedByName} звонит вам'),
        actions: [
          TextButton(
            style: TextButton.styleFrom(foregroundColor: Colors.red),
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Отклонить'),
          ),
          FilledButton.icon(
            onPressed: () => Navigator.of(ctx).pop(true),
            icon: const Icon(Icons.call, size: 18),
            label: const Text('Принять'),
          ),
        ],
      ),
    );
    // Диалог мог быть снят поллингом (accepted == null) — звонок уже отбит.
    final wasDismissedByPoll = _incomingCallId == null;
    _incomingCallId = null;
    if (wasDismissedByPoll || accepted == null) return;

    if (accepted != true) {
      try {
        await CallRepository.instance.end(call.id);
      } on Object {
        // Не дозвонились до сервера — звонок сам истечёт по таймауту.
      }
      return;
    }

    try {
      final token = await CallRepository.instance.token(call.roomName);
      _inCall = true;
      await nav.push(MaterialPageRoute(
        builder: (_) => CallScreen(
          token: token,
          remoteName: call.initiatedByName,
        ),
      ));
    } on Object {
      // Комната уже закрыта / сеть — просто не входим.
    } finally {
      _inCall = false;
    }
  }

  /// Пометить, что пользователь в звонке (исходящий вызов из чата) —
  /// на время звонка входящие не показываются.
  Future<T> withInCall<T>(Future<T> Function() body) async {
    _inCall = true;
    try {
      return await body();
    } finally {
      _inCall = false;
    }
  }
}
