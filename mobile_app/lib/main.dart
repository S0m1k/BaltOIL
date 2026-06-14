import 'package:flutter/material.dart';

import 'core/api_client.dart';
import 'core/sync_service.dart';
import 'core/token_storage.dart';
import 'features/auth/login_screen.dart';
import 'features/home/home_screen.dart';
import 'push/push_registrar.dart';

final navigatorKey = GlobalKey<NavigatorState>();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  PushRegistrar.instance.navigatorKey = navigatorKey;
  await PushRegistrar.instance.init();
  // Офлайн-очередь водителя: fire-and-forget до runApp (flush идёт фоново).
  // ignore: unawaited_futures
  SyncService.instance.init();

  ApiClient.instance.onSessionExpired = () {
    navigatorKey.currentState?.pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (_) => false,
    );
  };

  final hasSession = await TokenStorage.instance.hasSession;
  runApp(BaltOilApp(startLoggedIn: hasSession));
}

class BaltOilApp extends StatelessWidget {
  const BaltOilApp({super.key, required this.startLoggedIn});

  final bool startLoggedIn;

  @override
  Widget build(BuildContext context) {
    // Палитра веба (frontend/index.html :root): primary #0ea5e9, accent #10b981,
    // фон #eef2fb, текст #0f172a.
    const primary = Color(0xFF0EA5E9);
    const background = Color(0xFFEEF2FB);
    return MaterialApp(
      title: 'BALTOIL',
      navigatorKey: navigatorKey,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: primary,
          primary: primary,
          secondary: const Color(0xFF10B981),
          surface: Colors.white,
        ),
        scaffoldBackgroundColor: background,
        appBarTheme: const AppBarTheme(
          backgroundColor: background,
          surfaceTintColor: Colors.transparent,
        ),
        cardTheme: const CardThemeData(
          color: Colors.white,
          surfaceTintColor: Colors.transparent,
        ),
      ),
      home: startLoggedIn ? const HomeScreen() : const LoginScreen(),
    );
  }
}
