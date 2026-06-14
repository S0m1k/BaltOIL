import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Управление темой (светлая/тёмная) с персистом.
///
/// Совместимо с веб-версией: ключ хранения `theme`, значения `dark`/`light`.
/// Если значение не задано — следуем системной теме (как `prefers-color-scheme`
/// на вебе).
class ThemeController {
  ThemeController._();
  static final ThemeController instance = ThemeController._();

  static const _key = 'theme';

  final ValueNotifier<ThemeMode> mode = ValueNotifier(ThemeMode.system);

  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString(_key);
    mode.value = switch (saved) {
      'dark' => ThemeMode.dark,
      'light' => ThemeMode.light,
      _ => ThemeMode.system,
    };
  }

  /// Переключение между светлой и тёмной. Текущая системная тема нужна, чтобы
  /// первый тап от `system` ушёл в противоположную видимую тему.
  Future<void> toggle(Brightness current) async {
    final goingDark = mode.value == ThemeMode.light ||
        (mode.value == ThemeMode.system && current == Brightness.light);
    mode.value = goingDark ? ThemeMode.dark : ThemeMode.light;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_key, goingDark ? 'dark' : 'light');
  }
}
