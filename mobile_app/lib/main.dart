import 'package:flutter/material.dart';

import 'core/api_client.dart';
import 'core/sync_service.dart';
import 'core/theme.dart';
import 'core/theme_controller.dart';
import 'core/token_storage.dart';
import 'features/auth/login_screen.dart';
import 'features/calls/callkit_service.dart';
import 'features/calls/incoming_call_watcher.dart';
import 'features/home/home_screen.dart';
import 'push/push_registrar.dart';

final navigatorKey = GlobalKey<NavigatorState>();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  PushRegistrar.instance.navigatorKey = navigatorKey;
  IncomingCallWatcher.instance.navigatorKey = navigatorKey;
  // Нативная звонилка: слушаем accept/decline системного экрана звонка.
  CallkitService.instance.navigatorKey = navigatorKey;
  CallkitService.instance.listen();
  await PushRegistrar.instance.init();
  // Офлайн-очередь водителя: fire-and-forget до runApp (flush идёт фоново).
  // ignore: unawaited_futures
  SyncService.instance.init();

  // Экран входа показываем ОДИН раз на сессию. Поллинг звонков стучится раз
  // в 4 секунды: без этой защиты каждый его 401 заново сбрасывал стек
  // навигации — в том числе поверх экрана уже вошедшего пользователя.
  var loginShownForGen = -1;
  ApiClient.instance.onSessionExpired = () {
    final gen = TokenStorage.instance.generation;
    if (loginShownForGen == gen) return;
    loginShownForGen = gen;
    // Сессии больше нет — фоновые опросы обязаны замолчать, иначе они
    // продолжают долбить сервер без токена, пока идёт ввод логина.
    IncomingCallWatcher.instance.stop();
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
