import 'package:flutter/material.dart';

import 'core/api_client.dart';
import 'core/token_storage.dart';
import 'features/auth/login_screen.dart';
import 'features/home/home_screen.dart';
import 'push/push_registrar.dart';

final navigatorKey = GlobalKey<NavigatorState>();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await PushRegistrar.instance.init();

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
    return MaterialApp(
      title: 'БалтОйл',
      navigatorKey: navigatorKey,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF0B5394)),
        useMaterial3: true,
      ),
      home: startLoggedIn ? const HomeScreen() : const LoginScreen(),
    );
  }
}
