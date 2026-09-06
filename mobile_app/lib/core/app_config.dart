/// Конфигурация окружения.
///
/// ПРОД (режим по умолчанию, ничего передавать на сборке не нужно).
/// Все сервисы ходят через ЕДИНЫЙ TLS-шлюз на 443 с префиксами
/// `/api/<сервис>/` — ровно как веб-фронт (см. AUTH_URL/ORDER_URL/… в
/// frontend/index.html) и как nginx на проде:
///   /api/auth/…  → auth_service:8001
///   /api/order/… → order_service:8002
///   /api/delivery/… → delivery_service:8003
///   /api/chat/…  → chat_service:8004 (в т.ч. WebSocket /ws/<id>)
///   /api/notif/… → notification_service:8005
///   /api/call/…  → call_service:8006
///
/// Почему не порты 8001–8006 напрямую: они хоть и открыты на сервере, но
/// режутся по дороге (провайдеры/мобильные операторы часто пропускают только
/// 80/443). С телефона заказчицы такие адреса дают таймаут — приложение
/// выглядит «не коннектится к бэку». 443 доступен всегда и закрыт валидным
/// сертификатом Let's Encrypt на crm.9171517.ru.
///
/// ЛОКАЛЬНАЯ РАЗРАБОТКА — прежняя схема «хост + порт сервиса»:
///   flutter run \
///     --dart-define=API_HOST=10.0.2.2 \
///     --dart-define=API_DIRECT_PORTS=true \
///     --dart-define=ALLOW_BAD_CERTS=true
class AppConfig {
  /// Хост бэкенда без схемы и порта. Дефолт — прод, чтобы релизная сборка
  /// без единого --dart-define сразу смотрела куда надо.
  static const String apiHost = String.fromEnvironment(
    'API_HOST',
    defaultValue: 'crm.9171517.ru',
  );

  /// Ходить напрямую в порты сервисов (8001…8006) вместо шлюза на 443.
  /// Только для локального стенда, где nginx-шлюза может не быть.
  static const bool useDirectPorts = bool.fromEnvironment(
    'API_DIRECT_PORTS',
    defaultValue: false,
  );

  /// Разрешить самоподписанный сертификат (только для локальной разработки).
  /// По умолчанию false. В release-сборке игнорируется всегда — см.
  /// `core/api_client.dart` (проверка `!kReleaseMode`).
  static const bool allowBadCertificates = bool.fromEnvironment(
    'ALLOW_BAD_CERTS',
    defaultValue: false,
  );

  static String _http(String gatewayPath, int directPort, String directPath) =>
      useDirectPorts
          ? 'https://$apiHost:$directPort$directPath'
          : 'https://$apiHost$gatewayPath';

  static String get authBase =>
      _http('/api/auth/api/v1', 8001, '/api/v1');

  static String get orderBase =>
      _http('/api/order/api/v1', 8002, '/api/v1');

  static String get deliveryBase =>
      _http('/api/delivery/api/v1', 8003, '/api/v1');

  /// chat_service: роуты в КОРНЕ сервиса (без /api/v1) — как CHAT_URL='/api/chat'
  /// на вебе.
  static String get chatBase => _http('/api/chat', 8004, '');

  /// WebSocket чата: `$wsBase/ws/<conversation_id>`.
  static String get wsBase => useDirectPorts
      ? 'wss://$apiHost:8004'
      : 'wss://$apiHost/api/chat';

  static String get notificationBase =>
      _http('/api/notif/api/v1', 8005, '/api/v1');

  /// call_service (звонки): маршруты в корне, без /api/v1 —
  /// как CALL_URL='/api/call' на вебе.
  static String get callBase => _http('/api/call', 8006, '');
}
