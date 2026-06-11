import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:baltoil_mobile/main.dart';

void main() {
  testWidgets('login screen shows both tabs', (tester) async {
    await tester.pumpWidget(const BaltOilApp(startLoggedIn: false));

    expect(find.text('По паролю'), findsOneWidget);
    expect(find.text('По SMS-коду'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Войти'), findsOneWidget);
  });
}
