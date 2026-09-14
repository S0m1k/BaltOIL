import 'dart:io';

import 'package:flutter/material.dart';

/// Полноэкранный просмотр фото с зумом (правки 2026-09-14).
///
/// Раньше фото в чате было только превью 200 px без реакции на нажатие —
/// разглядеть накладную или показания счётчика было нельзя. Здесь: щипок для
/// увеличения до ×5, двойной тап — приблизить в точку касания и обратно.
/// Без внешних пакетов: встроенного InteractiveViewer достаточно.
class PhotoViewerScreen extends StatefulWidget {
  const PhotoViewerScreen({super.key, required this.file});

  final File file;

  // Hero-анимацию из превью намеренно не делаем: одно фото может оказаться в
  // ленте дважды (оптимистичное сообщение и эхо с сервера), а дубликат
  // Hero-тега роняет навигацию.
  static Future<void> open(BuildContext context, File file) {
    return Navigator.of(context).push(
      PageRouteBuilder<void>(
        opaque: false,
        barrierColor: Colors.black,
        pageBuilder: (_, _, _) => PhotoViewerScreen(file: file),
        transitionsBuilder: (_, animation, _, child) =>
            FadeTransition(opacity: animation, child: child),
      ),
    );
  }

  @override
  State<PhotoViewerScreen> createState() => _PhotoViewerScreenState();
}

class _PhotoViewerScreenState extends State<PhotoViewerScreen>
    with SingleTickerProviderStateMixin {
  static const _maxScale = 5.0;
  static const _doubleTapScale = 2.5;

  final _transform = TransformationController();
  late final AnimationController _zoomAnim;
  Animation<Matrix4>? _zoomTween;
  Offset _doubleTapAt = Offset.zero;

  @override
  void initState() {
    super.initState();
    _zoomAnim =
        AnimationController(
          vsync: this,
          duration: const Duration(milliseconds: 220),
        )..addListener(() {
          final tween = _zoomTween;
          if (tween != null) _transform.value = tween.value;
        });
  }

  @override
  void dispose() {
    _zoomAnim.dispose();
    _transform.dispose();
    super.dispose();
  }

  void _onDoubleTap() {
    final current = _transform.value;
    final zoomedIn = current.getMaxScaleOnAxis() > 1.01;
    final Matrix4 target;
    if (zoomedIn) {
      target = Matrix4.identity();
    } else {
      // Масштаб вокруг точки касания: сдвигаем так, чтобы она осталась
      // под пальцем, а не уезжала к левому верхнему углу.
      final p = _doubleTapAt;
      target = Matrix4.identity()
        ..setEntry(0, 0, _doubleTapScale)
        ..setEntry(1, 1, _doubleTapScale)
        ..setEntry(0, 3, -p.dx * (_doubleTapScale - 1))
        ..setEntry(1, 3, -p.dy * (_doubleTapScale - 1));
    }
    _zoomTween = Matrix4Tween(
      begin: current,
      end: target,
    ).animate(CurvedAnimation(parent: _zoomAnim, curve: Curves.easeOut));
    _zoomAnim.forward(from: 0);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        children: [
          Positioned.fill(
            child: GestureDetector(
              onDoubleTapDown: (d) => _doubleTapAt = d.localPosition,
              onDoubleTap: _onDoubleTap,
              child: InteractiveViewer(
                transformationController: _transform,
                maxScale: _maxScale,
                child: Center(
                  child: Image.file(widget.file, fit: BoxFit.contain),
                ),
              ),
            ),
          ),
          SafeArea(
            child: Align(
              alignment: Alignment.topRight,
              child: Padding(
                padding: const EdgeInsets.all(8),
                child: IconButton.filled(
                  style: IconButton.styleFrom(
                    backgroundColor: Colors.black54,
                    foregroundColor: Colors.white,
                  ),
                  tooltip: 'Закрыть',
                  icon: const Icon(Icons.close),
                  onPressed: () => Navigator.of(context).maybePop(),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
