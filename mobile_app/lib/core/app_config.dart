/// Конфигурация окружения.
///
/// Бэкенд — микросервисы на разных портах за одним TLS-прокси:
///   8001 auth, 8002 order, 8004 chat, 8005 notification.
///
/// Хост задаётся на сборке: flutter run --dart-define=API_HOST=baltoil.example.ru
/// Дефолт 10.0.2.2 — это localhost хоста из Android-эмулятора.
class AppConfig {
  static const String apiHost = String.fromEnvironment(
    'API_HOST',
    defaultValue: '10.0.2.2',
  );

  /// Разрешить самоподписанный сертификат (только для локальной разработки).
  /// По умолчанию false — пробросить true только если TLS-прокси использует
  /// самоподписанный сертификат (локальный стенд). На проде всегда false.
  static const bool allowBadCertificates = bool.fromEnvironment(
    'ALLOW_BAD_CERTS',
    defaultValue: false,
  );

  static String get authBase => 'https://$apiHost:8001/api/v1';
  static String get orderBase => 'https://$apiHost:8002/api/v1';

  /// chat_service: роуты в КОРНЕ (без /api/v1) — как CHAT_URL='/api/chat'
  /// на вебе; nginx на :8004 проксирует / без переписывания пути.
  static String get chatBase => 'https://$apiHost:8004';
  static String get wsBase => 'wss://$apiHost:8004';
  static String get notificationBase => 'https://$apiHost:8005/api/v1';
  static String get deliveryBase => 'https://$apiHost:8003/api/v1';

  /// call_service (звонки): маршруты в корне, без /api/v1 —
  /// как CALL_URL='/api/call' на вебе (nginx срезает префикс).
  static String get callBase => 'https://$apiHost:8006';
}
