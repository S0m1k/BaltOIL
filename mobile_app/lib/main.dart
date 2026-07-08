import 'package:flutter/material.dart';

import 'core/api_client.dart';
import 'core/sync_service.dart';
import 'core/theme.dart';
import 'core/theme_controller.dart';
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

  await ThemeController.instance.load();
  final hasSession = await TokenStorage.instance.hasSession;
  runApp(BaltOilApp(startLoggedIn: hasSession));
}

class BaltOilApp extends StatelessWidget {
  const BaltOilApp({super.key, required this.startLoggedIn});

  final bool startLoggedIn;

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<ThemeMode>(
      valueListenable: ThemeController.instance.mode,
      builder: (context, mode, _) {
        return MaterialApp(
          title: 'СЗТК',
          navigatorKey: navigatorKey,
          debugShowCheckedModeBanner: false,
          theme: buildLightTheme(),
          darkTheme: buildDarkTheme(),
          themeMode: mode,
          home: startLoggedIn ? const HomeScreen() : const LoginScreen(),
        );
      },
    );
  }
}
