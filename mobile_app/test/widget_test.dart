import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:baltoil_mobile/main.dart';

void main() {
  // Вход по SMS скрыт как на вебе (d89ff92) — вкладок больше нет,
  // сразу форма входа по паролю.
  testWidgets('login screen shows the password form without tabs',
      (tester) async {
    await tester.pumpWidget(const BaltOilApp(startLoggedIn: false));

    expect(find.widgetWithText(FilledButton, 'Войти'), findsOneWidget);
    expect(find.byType(TabBar), findsNothing);
    expect(find.text('По SMS-коду'), findsNothing);
  });
}
