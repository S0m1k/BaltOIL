/// Конфигурация окружения.
///
/// Бэкенд — микросервисы на разных портах за одним TLS-прокси:
///   8001 auth, 8002 order, 8005 notification.
///
/// Хост задаётся на сборке: flutter run --dart-define=API_HOST=baltoil.example.ru
/// Дефолт 10.0.2.2 — это localhost хоста из Android-эмулятора.
class AppConfig {
  static const String apiHost = String.fromEnvironment(
    'API_HOST',
    defaultValue: '10.0.2.2',
  );

  /// Разрешить самоподписанный сертификат (только для локальной разработки).
  static const bool allowBadCertificates = bool.fromEnvironment(
    'ALLOW_BAD_CERTS',
    defaultValue: true,
  );

  static String get authBase => 'https://$apiHost:8001/api/v1';
  static String get orderBase => 'https://$apiHost:8002/api/v1';
  static String get notificationBase => 'https://$apiHost:8005/api/v1';
}
