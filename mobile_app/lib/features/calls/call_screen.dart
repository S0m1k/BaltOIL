import 'dart:async';

import 'package:flutter/material.dart';
import 'package:livekit_client/livekit_client.dart' as lk;
import 'package:wakelock_plus/wakelock_plus.dart';

import '../../core/api_client.dart';
import 'call_repository.dart';

/// Экран активного звонка (зеркало веб-модалки _enterRoom, 2026-07):
/// аудио-звонок через LiveKit — mute, динамик, таймер, отбой.
/// Камера, как и на вебе, не публикуется.
class CallScreen extends StatefulWidget {
  const CallScreen({
    super.key,
    required this.token,
    required this.remoteName,
  });

  /// Токен и адрес комнаты, полученные из /calls/start или /calls/token.
  final CallToken token;

  /// Имя собеседника (или названия диалога) для шапки до подключения.
  final String remoteName;

  @override
  State<CallScreen> createState() => _CallScreenState();
}

class _CallScreenState extends State<CallScreen> {
  lk.Room? _room;
  lk.EventsListener<lk.RoomEvent>? _listener;
  bool _connecting = true;
  bool _muted = false;
  bool _speakerOn = false;
  bool _cameraOn = false;
  String? _error;
  String _statusLabel = 'Соединение…';
  DateTime? _startedAt;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    // З1 (правки 2026-07-21): экран не гаснет во время звонка — иначе Android
    // уходит в спящий режим и усыпляет аудиопоток LiveKit до разблокировки.
    // ignore: discarded_futures
    WakelockPlus.enable();
    _connect();
  }

  @override
  void dispose() {
    // ignore: discarded_futures
    WakelockPlus.disable();
    _timer?.cancel();
    _listener?.dispose();
    _room?.dispose();
    super.dispose();
  }

  Future<void> _connect() async {
    final room = lk.Room(
      roomOptions: const lk.RoomOptions(
        adaptiveStream: true,
        dynacast: true,
        defaultAudioCaptureOptions: lk.AudioCaptureOptions(
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        ),
      ),
    );
    _room = room;
    final listener = room.createListener();
    _listener = listener;
    listener
      ..on<lk.ParticipantConnectedEvent>((_) => _syncState())
      ..on<lk.ParticipantDisconnectedEvent>((_) => _syncState())
      ..on<lk.TrackSubscribedEvent>((_) => _syncState())
      // Видео (2026-07-17): перестраиваем сетку плиток при публикации
      // и снятии видеотреков — своих и удалённых.
      ..on<lk.TrackUnsubscribedEvent>((_) => _syncState())
      ..on<lk.LocalTrackPublishedEvent>((_) => _syncState())
      ..on<lk.LocalTrackUnpublishedEvent>((_) => _syncState())
      ..on<lk.TrackMutedEvent>((_) => _syncState())
      ..on<lk.TrackUnmutedEvent>((_) => _syncState())
      ..on<lk.RoomDisconnectedEvent>((_) {
        // Собеседник завершил звонок / комната закрыта. Явный pop():
        // maybePop() уважает canPop:false у PopScope и не закрыл бы экран.
        _leave();
      });
    try {
      await room.connect(widget.token.livekitUrl, widget.token.token);
      await room.localParticipant?.setMicrophoneEnabled(true);
      if (!mounted) return;
      setState(() => _connecting = false);
      _syncState();
    } on Object catch (e) {
      if (!mounted) return;
      setState(() {
        _connecting = false;
        _error = apiErrorMessage(e);
      });
    }
  }

  /// «Ожидание ответа…» → «В звонке» при появлении собеседника
  /// (веб _maybeStartTimer/_updateHeader).
  void _syncState() {
    final room = _room;
    if (room == null || !mounted) return;
    final remotes = room.remoteParticipants.values.toList();
    setState(() {
      if (remotes.isEmpty) {
        _statusLabel = 'Ожидание ответа…';
      } else {
        _statusLabel = 'В звонке';
        if (_startedAt == null) {
          _startedAt = DateTime.now();
          _timer = Timer.periodic(
              const Duration(seconds: 1), (_) => setState(() {}));
        }
      }
    });
  }

  String get _remoteLabel {
    final remotes = _room?.remoteParticipants.values.toList() ?? const [];
    if (remotes.isEmpty) return widget.remoteName;
    final names = [
      for (final p in remotes)
        if ((p.name).isNotEmpty) p.name else p.identity,
    ];
    if (names.length == 1) return names.first;
    return '${names.first} и ещё ${names.length - 1}';
  }

  String get _elapsed {
    final started = _startedAt;
    if (started == null) return '';
    final d = DateTime.now().difference(started);
    final m = d.inMinutes.toString().padLeft(2, '0');
    final s = (d.inSeconds % 60).toString().padLeft(2, '0');
    return '$m:$s';
  }

  Future<void> _toggleMute() async {
    final lp = _room?.localParticipant;
    if (lp == null) return;
    await lp.setMicrophoneEnabled(_muted); // _muted=true → включить обратно
    setState(() => _muted = !_muted);
  }

  Future<void> _toggleSpeaker() async {
    final next = !_speakerOn;
    try {
      await lk.Hardware.instance.setSpeakerphoneOn(next);
      setState(() => _speakerOn = next);
    } on Object {
      // Не критично: остаёмся на текущем аудиовыходе.
    }
  }

  /// Камера (веб toggleCallCamera): публикуем/снимаем видеотрек.
  /// По умолчанию фронтальная; собеседник получит его через подписку.
  Future<void> _toggleCamera() async {
    final lp = _room?.localParticipant;
    if (lp == null) return;
    try {
      await lp.setCameraEnabled(!_cameraOn);
      setState(() => _cameraOn = !_cameraOn);
    } on Object catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('Не удалось включить камеру: '
                '${apiErrorMessage(e)}')));
      }
    }
  }

  /// Видеоплитки: свои + удалённые видеотреки (веб conf-tiles).
  List<({String label, lk.VideoTrack track, bool isLocal})> get _videoTiles {
    final room = _room;
    if (room == null) return const [];
    final tiles = <({String label, lk.VideoTrack track, bool isLocal})>[];
    final lp = room.localParticipant;
    if (lp != null) {
      for (final pub in lp.videoTrackPublications) {
        final track = pub.track;
        if (track != null && !pub.muted) {
          tiles.add((label: 'Вы', track: track, isLocal: true));
        }
      }
    }
    for (final p in room.remoteParticipants.values) {
      for (final pub in p.videoTrackPublications) {
        final track = pub.track;
        if (track != null && pub.subscribed && !pub.muted) {
          tiles.add((
            label: p.name.isNotEmpty ? p.name : p.identity,
            track: track,
            isLocal: false,
          ));
        }
      }
    }
    return tiles;
  }

  bool _leaving = false;

  /// Единственная точка выхода с экрана. Navigator.pop() — а не maybePop(),
  /// который блокируется собственным PopScope(canPop: false).
  void _leave() {
    if (_leaving || !mounted) return;
    _leaving = true;
    Navigator.of(context).pop();
  }

  Future<void> _hangUp() async {
    if (_leaving) return;
    // Завершаем на сервере (комната закроется для всех), затем выходим.
    // Экран закрываем сразу — сетевые вызовы не должны держать кнопку.
    final callId = widget.token.callId;
    final room = _room;
    _leave();
    try {
      await CallRepository.instance.end(callId);
    } on Object {
      // Даже если сервер недоступен — отключаемся локально.
    }
    try {
      await room?.disconnect();
    } on Object {
      // Комната могла уже закрыться сервером.
    }
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _hangUp();
      },
      child: Scaffold(
        backgroundColor: const Color(0xFF10151D),
        body: SafeArea(
          child: Column(
            children: [
              // Сетка видео, когда хоть у кого-то включена камера;
              // иначе — классический аудио-экран с аватаром.
              if (_videoTiles.isNotEmpty) ...[
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                  child: Text(
                    _error ??
                        (_startedAt != null
                            ? '$_remoteLabel · $_elapsed'
                            : '$_remoteLabel · $_statusLabel'),
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      color: _error != null
                          ? Colors.red.shade300
                          : Colors.white70,
                      fontSize: 14,
                    ),
                  ),
                ),
                Expanded(child: _VideoGrid(tiles: _videoTiles)),
              ] else ...[
                const Spacer(),
                const CircleAvatar(
                  radius: 44,
                  backgroundColor: Color(0xFF1F2937),
                  child: Icon(Icons.person, size: 48, color: Colors.white70),
                ),
                const SizedBox(height: 20),
                Text(
                  _remoteLabel,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 22,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  _error ??
                      (_connecting
                          ? 'Соединение…'
                          : _startedAt != null
                              ? '$_statusLabel · $_elapsed'
                              : _statusLabel),
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color:
                        _error != null ? Colors.red.shade300 : Colors.white60,
                    fontSize: 14,
                  ),
                ),
                const Spacer(),
              ],
              Padding(
                padding: const EdgeInsets.only(bottom: 40),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                  children: [
                    _RoundButton(
                      icon: _muted ? Icons.mic_off : Icons.mic,
                      label: _muted ? 'Вкл. микрофон' : 'Микрофон',
                      background:
                          _muted ? Colors.white24 : const Color(0xFF1F2937),
                      onTap: _toggleMute,
                    ),
                    _RoundButton(
                      icon: _cameraOn
                          ? Icons.videocam
                          : Icons.videocam_off_outlined,
                      label: 'Камера',
                      background: _cameraOn
                          ? Colors.white24
                          : const Color(0xFF1F2937),
                      onTap: _toggleCamera,
                    ),
                    _RoundButton(
                      icon: Icons.call_end,
                      label: 'Завершить',
                      background: Colors.red.shade700,
                      size: 68,
                      onTap: _hangUp,
                    ),
                    _RoundButton(
                      icon: _speakerOn ? Icons.volume_up : Icons.volume_down,
                      label: 'Динамик',
                      background: _speakerOn
                          ? Colors.white24
                          : const Color(0xFF1F2937),
                      onTap: _toggleSpeaker,
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

/// Сетка видеоплиток (веб conf-tiles): 1 участник — во весь экран,
/// больше — по 2 в ряд. Локальное превью зеркалится.
class _VideoGrid extends StatelessWidget {
  const _VideoGrid({required this.tiles});

  final List<({String label, lk.VideoTrack track, bool isLocal})> tiles;

  @override
  Widget build(BuildContext context) {
    if (tiles.length == 1) {
      return Padding(
        padding: const EdgeInsets.all(12),
        child: _VideoTile(tile: tiles.first),
      );
    }
    return GridView.builder(
      padding: const EdgeInsets.all(12),
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: 2,
        mainAxisSpacing: 10,
        crossAxisSpacing: 10,
        childAspectRatio: 3 / 4,
      ),
      itemCount: tiles.length,
      itemBuilder: (context, i) => _VideoTile(tile: tiles[i]),
    );
  }
}

class _VideoTile extends StatelessWidget {
  const _VideoTile({required this.tile});

  final ({String label, lk.VideoTrack track, bool isLocal}) tile;

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(14),
      child: Stack(
        fit: StackFit.expand,
        children: [
          Container(color: const Color(0xFF1F2937)),
          lk.VideoTrackRenderer(
            tile.track,
            fit: lk.VideoViewFit.cover,
            mirrorMode: tile.isLocal
                ? lk.VideoViewMirrorMode.mirror
                : lk.VideoViewMirrorMode.off,
          ),
          Positioned(
            left: 8,
            bottom: 8,
            child: Container(
              padding:
                  const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              decoration: BoxDecoration(
                color: Colors.black54,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                tile.label,
                style:
                    const TextStyle(color: Colors.white, fontSize: 12),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _RoundButton extends StatelessWidget {
  const _RoundButton({
    required this.icon,
    required this.label,
    required this.background,
    required this.onTap,
    this.size = 56,
  });

  final IconData icon;
  final String label;
  final Color background;
  final VoidCallback onTap;
  final double size;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Material(
          color: background,
          shape: const CircleBorder(),
          child: InkWell(
            customBorder: const CircleBorder(),
            onTap: onTap,
            child: SizedBox(
              width: size,
              height: size,
              child: Icon(icon, color: Colors.white, size: size * 0.45),
            ),
          ),
        ),
        const SizedBox(height: 6),
        Text(label,
            style: const TextStyle(color: Colors.white60, fontSize: 11)),
      ],
    );
  }
}
