import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_ringtone_player/flutter_ringtone_player.dart';

import 'call_repository.dart';

/// Полноэкранный входящий звонок (правки 2026-07-22).
///
/// Показывается, когда приложение открыто (из пуша call_initiated или
/// поллера) — вместо callkit-шторки, у которой MIUI обрезал рингтон после
/// одного-двух гудков. Системный рингтон зациклен на весь показ экрана.
/// Для фона/убитого приложения остаётся системный экран callkit.
///
/// Возвращает `true` (принять), `false` (отклонить); если звонок пропал
/// (инициатор отбил) — закрывается сам с `null`.
class IncomingCallScreen extends StatefulWidget {
  const IncomingCallScreen({super.key, required this.call});

  final CallInfo call;

  @override
  State<IncomingCallScreen> createState() => _IncomingCallScreenState();
}

class _IncomingCallScreenState extends State<IncomingCallScreen> {
  Timer? _statusTimer;
  bool _closing = false;

  @override
  void initState() {
    super.initState();
    // Зацикленный системный рингтон — играет, пока экран на месте.
    // ignore: discarded_futures
    FlutterRingtonePlayer().playRingtone(looping: true, volume: 1.0);
    // Инициатор мог отбить: раз в 2 с проверяем, что звонок ещё ringing.
    _statusTimer = Timer.periodic(const Duration(seconds: 2), (_) async {
      try {
        final c = await CallRepository.instance.getCall(widget.call.id);
        if (c.status != 'ringing') _close(null);
      } on Object {
        // Сервер моргнул — не снимаем экран, звонок истечёт по таймауту.
      }
    });
  }

  @override
  void dispose() {
    _statusTimer?.cancel();
    // ignore: discarded_futures
    FlutterRingtonePlayer().stop();
    super.dispose();
  }

  void _close(bool? result) {
    if (_closing || !mounted) return;
    _closing = true;
    Navigator.of(context).pop(result);
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false, // отвечаем кнопками, а не свайпом назад
      child: Scaffold(
        backgroundColor: const Color(0xFF10151D),
        body: SafeArea(
          child: Column(
            children: [
              const Spacer(flex: 2),
              const Text(
                'Входящий звонок',
                style: TextStyle(color: Colors.white60, fontSize: 16),
              ),
              const SizedBox(height: 24),
              CircleAvatar(
                radius: 56,
                backgroundColor: const Color(0xFF0EA5E9).withValues(alpha: .2),
                child: const Icon(Icons.person,
                    size: 64, color: Color(0xFF0EA5E9)),
              ),
              const SizedBox(height: 24),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 24),
                child: Text(
                  widget.call.initiatedByName,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 26,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                'СЗТК · аудиозвонок',
                style: TextStyle(color: Colors.white38, fontSize: 13),
              ),
              const Spacer(flex: 3),
              Padding(
                padding: const EdgeInsets.only(bottom: 48),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                  children: [
                    _RoundAction(
                      color: Colors.red,
                      icon: Icons.call_end,
                      label: 'Отклонить',
                      onTap: () => _close(false),
                    ),
                    _RoundAction(
                      color: const Color(0xFF22C55E),
                      icon: Icons.call,
                      label: 'Принять',
                      onTap: () => _close(true),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _RoundAction extends StatelessWidget {
  const _RoundAction({
    required this.color,
    required this.icon,
    required this.label,
    required this.onTap,
  });

  final Color color;
  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Material(
          color: color,
          shape: const CircleBorder(),
          child: InkWell(
            customBorder: const CircleBorder(),
            onTap: onTap,
            child: SizedBox(
              width: 72,
              height: 72,
              child: Icon(icon, color: Colors.white, size: 32),
            ),
          ),
        ),
        const SizedBox(height: 10),
        Text(label,
            style: const TextStyle(color: Colors.white70, fontSize: 13)),
      ],
    );
  }
}
