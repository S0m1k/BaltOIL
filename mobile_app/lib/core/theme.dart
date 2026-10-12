import 'package:flutter/material.dart';

/// Дизайн-токены веба (frontend/index.html `:root` и `html.dark`),
/// перенесённые 1-в-1. Доступ из виджетов: `context.colors`.
///
/// Палитра, типографика и статус-цвета должны совпадать с веб-версией —
/// заказчик требует консистентность мобилки с вебом.
@immutable
class AppColors extends ThemeExtension<AppColors> {
  const AppColors({
    required this.bg,
    required this.bg2,
    required this.bg3,
    required this.border,
    required this.border2,
    required this.primary,
    required this.primary2,
    required this.primaryDim,
    required this.accent,
    required this.accent2,
    required this.accentDim,
    required this.text,
    required this.text2,
    required this.text3,
    required this.red,
    required this.green,
    required this.statusNew,
    required this.statusProgress,
    required this.statusDelivered,
    required this.statusClosed,
    required this.statusRejected,
    required this.roleAdmin,
    required this.roleManager,
    required this.roleDriver,
    required this.roleClient,
  });

  final Color bg; // --bg
  final Color bg2; // --bg2 (surface/card)
  final Color bg3; // --bg3
  final Color border; // --border
  final Color border2; // --border2
  final Color primary; // --amber
  final Color primary2; // --amber2
  final Color primaryDim; // --amber-dim
  final Color accent; // --accent
  final Color accent2; // --accent2
  final Color accentDim; // --accent-dim
  final Color text; // --text
  final Color text2; // --text2
  final Color text3; // --text3
  final Color red; // --red
  final Color green; // --green
  final Color statusNew; // --s-new
  final Color statusProgress; // --s-progress
  final Color statusDelivered; // --s-delivered
  final Color statusClosed; // --s-closed
  final Color statusRejected; // --s-rejected
  final Color roleAdmin;
  final Color roleManager;
  final Color roleDriver;
  final Color roleClient;

  /// Цвет статуса заявки по ключу (new/awaiting_manager/accepted/delivered/cancelled).
  Color statusColor(String status) => switch (status) {
        'new' => statusNew,
        'awaiting_manager' => primary,
        'accepted' => statusProgress,
        'delivered' => statusDelivered,
        'cancelled' => statusRejected,
        _ => text3,
      };

  /// Цвет чипа роли (admin/manager/driver/client).
  Color roleColor(String role) => switch (role) {
        'admin' => roleAdmin,
        'manager' => roleManager,
        'driver' => roleDriver,
        'client' => roleClient,
        _ => text3,
      };

  static const light = AppColors(
    bg: Color(0xFFEEF2FB),
    bg2: Color(0xFFFFFFFF),
    bg3: Color(0xFFF4F7FD),
    border: Color(0xFFDDE3F0),
    border2: Color(0xFFC8D2E8),
    primary: Color(0xFF0EA5E9),
    primary2: Color(0xFF0284C7),
    primaryDim: Color(0x1A0EA5E9), // rgba(14,165,233,.10)
    accent: Color(0xFF10B981),
    accent2: Color(0xFF059669),
    accentDim: Color(0x1A10B981),
    text: Color(0xFF0F172A),
    text2: Color(0xFF334155),
    text3: Color(0xFF94A3B8),
    red: Color(0xFFEF4444),
    green: Color(0xFF10B981),
    statusNew: Color(0xFF3B82F6),
    statusProgress: Color(0xFFD97706),
    statusDelivered: Color(0xFF0D9488),
    statusClosed: Color(0xFF6B7280),
    statusRejected: Color(0xFFDC2626),
    roleAdmin: Color(0xFFB91C1C),
    roleManager: Color(0xFF0369A1),
    roleDriver: Color(0xFF6D28D9),
    roleClient: Color(0xFF047857),
  );

  static const dark = AppColors(
    bg: Color(0xFF0F172A),
    bg2: Color(0xFF1E293B),
    bg3: Color(0xFF1A2236),
    border: Color(0xFF334155),
    border2: Color(0xFF475569),
    primary: Color(0xFF38BDF8),
    primary2: Color(0xFF0EA5E9),
    primaryDim: Color(0x1F38BDF8), // rgba(56,189,248,.12)
    accent: Color(0xFF34D399),
    accent2: Color(0xFF10B981),
    accentDim: Color(0x1F34D399),
    text: Color(0xFFF1F5F9),
    text2: Color(0xFFCBD5E1),
    text3: Color(0xFF64748B),
    red: Color(0xFFF87171),
    green: Color(0xFF34D399),
    // Статус-цвета общие для обеих тем (как в вебе).
    statusNew: Color(0xFF3B82F6),
    statusProgress: Color(0xFFD97706),
    statusDelivered: Color(0xFF0D9488),
    statusClosed: Color(0xFF6B7280),
    statusRejected: Color(0xFFDC2626),
    roleAdmin: Color(0xFFFCA5A5),
    roleManager: Color(0xFF7DD3FC),
    roleDriver: Color(0xFFC4B5FD),
    roleClient: Color(0xFF6EE7B7),
  );

  @override
  AppColors copyWith({
    Color? bg,
    Color? bg2,
    Color? bg3,
    Color? border,
    Color? border2,
    Color? primary,
    Color? primary2,
    Color? primaryDim,
    Color? accent,
    Color? accent2,
    Color? accentDim,
    Color? text,
    Color? text2,
    Color? text3,
    Color? red,
    Color? green,
    Color? statusNew,
    Color? statusProgress,
    Color? statusDelivered,
    Color? statusClosed,
    Color? statusRejected,
    Color? roleAdmin,
    Color? roleManager,
    Color? roleDriver,
    Color? roleClient,
  }) {
    return AppColors(
      bg: bg ?? this.bg,
      bg2: bg2 ?? this.bg2,
      bg3: bg3 ?? this.bg3,
      border: border ?? this.border,
      border2: border2 ?? this.border2,
      primary: primary ?? this.primary,
      primary2: primary2 ?? this.primary2,
      primaryDim: primaryDim ?? this.primaryDim,
      accent: accent ?? this.accent,
      accent2: accent2 ?? this.accent2,
      accentDim: accentDim ?? this.accentDim,
      text: text ?? this.text,
      text2: text2 ?? this.text2,
      text3: text3 ?? this.text3,
      red: red ?? this.red,
      green: green ?? this.green,
      statusNew: statusNew ?? this.statusNew,
      statusProgress: statusProgress ?? this.statusProgress,
      statusDelivered: statusDelivered ?? this.statusDelivered,
      statusClosed: statusClosed ?? this.statusClosed,
      statusRejected: statusRejected ?? this.statusRejected,
      roleAdmin: roleAdmin ?? this.roleAdmin,
      roleManager: roleManager ?? this.roleManager,
      roleDriver: roleDriver ?? this.roleDriver,
      roleClient: roleClient ?? this.roleClient,
    );
  }

  @override
  AppColors lerp(ThemeExtension<AppColors>? other, double t) {
    if (other is! AppColors) return this;
    return AppColors(
      bg: Color.lerp(bg, other.bg, t)!,
      bg2: Color.lerp(bg2, other.bg2, t)!,
      bg3: Color.lerp(bg3, other.bg3, t)!,
      border: Color.lerp(border, other.border, t)!,
      border2: Color.lerp(border2, other.border2, t)!,
      primary: Color.lerp(primary, other.primary, t)!,
      primary2: Color.lerp(primary2, other.primary2, t)!,
      primaryDim: Color.lerp(primaryDim, other.primaryDim, t)!,
      accent: Color.lerp(accent, other.accent, t)!,
      accent2: Color.lerp(accent2, other.accent2, t)!,
      accentDim: Color.lerp(accentDim, other.accentDim, t)!,
      text: Color.lerp(text, other.text, t)!,
      text2: Color.lerp(text2, other.text2, t)!,
      text3: Color.lerp(text3, other.text3, t)!,
      red: Color.lerp(red, other.red, t)!,
      green: Color.lerp(green, other.green, t)!,
      statusNew: Color.lerp(statusNew, other.statusNew, t)!,
      statusProgress: Color.lerp(statusProgress, other.statusProgress, t)!,
      statusDelivered: Color.lerp(statusDelivered, other.statusDelivered, t)!,
      statusClosed: Color.lerp(statusClosed, other.statusClosed, t)!,
      statusRejected: Color.lerp(statusRejected, other.statusRejected, t)!,
      roleAdmin: Color.lerp(roleAdmin, other.roleAdmin, t)!,
      roleManager: Color.lerp(roleManager, other.roleManager, t)!,
      roleDriver: Color.lerp(roleDriver, other.roleDriver, t)!,
      roleClient: Color.lerp(roleClient, other.roleClient, t)!,
    );
  }
}

/// Удобный доступ к токенам: `context.colors.primary`.
extension AppColorsX on BuildContext {
  AppColors get colors => Theme.of(this).extension<AppColors>()!;
}

/// Подписи статусов заявок (web STATUS_LABELS).
const Map<String, String> kStatusLabels = {
  'new': 'Новая',
  'awaiting_manager': 'На согласовании',
  'accepted': 'Принята водителем',
  'delivered': 'Доставлена',
  'cancelled': 'Отменена',
};

const String _fontFamily = 'PlusJakartaSans';

ThemeData _build(AppColors c, Brightness brightness) {
  final scheme = ColorScheme.fromSeed(
    seedColor: c.primary,
    brightness: brightness,
    primary: c.primary,
    secondary: c.accent,
    surface: c.bg2,
    error: c.red,
  );
  return ThemeData(
    useMaterial3: true,
    fontFamily: _fontFamily,
    brightness: brightness,
    colorScheme: scheme,
    scaffoldBackgroundColor: c.bg,
    extensions: [c],
    appBarTheme: AppBarTheme(
      backgroundColor: c.bg,
      foregroundColor: c.text,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      titleTextStyle: TextStyle(
        fontFamily: _fontFamily,
        fontSize: 20,
        fontWeight: FontWeight.w700,
        letterSpacing: 0.5,
        color: c.text,
      ),
    ),
    cardTheme: CardThemeData(
      color: c.bg2,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: BorderSide(color: c.border),
      ),
    ),
    drawerTheme: DrawerThemeData(
      backgroundColor: c.bg2,
      surfaceTintColor: Colors.transparent,
    ),
    dividerTheme: DividerThemeData(color: c.border, thickness: 1),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: c.bg2,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(6),
        borderSide: BorderSide(color: c.border),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(6),
        borderSide: BorderSide(color: c.border),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(6),
        borderSide: BorderSide(color: c.primary, width: 2),
      ),
      labelStyle: TextStyle(color: c.text3),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: c.primary,
        foregroundColor: Colors.white,
        shape: const StadiumBorder(),
        textStyle: const TextStyle(
          fontFamily: _fontFamily,
          fontSize: 15,
          fontWeight: FontWeight.w600,
          letterSpacing: 1,
        ),
      ),
    ),
    textTheme: Typography.material2021(platform: TargetPlatform.android)
        .black
        .apply(
          fontFamily: _fontFamily,
          bodyColor: c.text,
          displayColor: c.text,
        ),
  );
}

ThemeData buildLightTheme() => _build(AppColors.light, Brightness.light);
ThemeData buildDarkTheme() => _build(AppColors.dark, Brightness.dark);
