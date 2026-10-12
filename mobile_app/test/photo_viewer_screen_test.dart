import 'dart:convert';
import 'dart:io';

import 'package:baltoil_mobile/features/common/photo_viewer_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Полноэкранный просмотр фото из чата (правки 2026-09-14): раньше фото
/// нельзя было ни открыть, ни увеличить.
void main() {
  // Минимальный валидный PNG 1×1 — сам просмотрщик картинку не разбирает,
  // но Image.file должен получить настоящий файл.
  final png1x1 = base64Decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg==',
  );

  late File photo;

  setUpAll(() {
    final dir = Directory.systemTemp.createTempSync('photo_viewer_test');
    photo = File('${dir.path}/photo.png')..writeAsBytesSync(png1x1);
  });

  Matrix4 currentTransform(WidgetTester tester) => tester
      .widget<InteractiveViewer>(find.byType(InteractiveViewer))
      .transformationController!
      .value;

  Future<void> openViewer(WidgetTester tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              onPressed: () => PhotoViewerScreen.open(context, photo),
              child: const Text('превью'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('превью'));
    await tester.pumpAndSettle();
  }

  Future<void> doubleTapCenter(WidgetTester tester) async {
    final center = tester.getCenter(find.byType(InteractiveViewer));
    await tester.tapAt(center);
    await tester.pump(const Duration(milliseconds: 50));
    await tester.tapAt(center);
    await tester.pumpAndSettle();
  }

  testWidgets('открывается без увеличения и разрешает зум до ×5', (
    tester,
  ) async {
    await openViewer(tester);

    expect(find.byType(PhotoViewerScreen), findsOneWidget);
    final viewer = tester.widget<InteractiveViewer>(
      find.byType(InteractiveViewer),
    );
    expect(viewer.maxScale, 5.0);
    expect(currentTransform(tester).getMaxScaleOnAxis(), 1.0);
  });

  testWidgets('двойной тап приближает, повторный — возвращает как было', (
    tester,
  ) async {
    await openViewer(tester);

    await doubleTapCenter(tester);
    expect(currentTransform(tester).getMaxScaleOnAxis(), closeTo(2.5, 0.01));

    await doubleTapCenter(tester);
    expect(currentTransform(tester).getMaxScaleOnAxis(), closeTo(1.0, 0.01));
  });

  testWidgets('кнопка «Закрыть» возвращает в чат', (tester) async {
    await openViewer(tester);

    await tester.tap(find.byTooltip('Закрыть'));
    await tester.pumpAndSettle();

    expect(find.byType(PhotoViewerScreen), findsNothing);
    expect(find.text('превью'), findsOneWidget);
  });
}
