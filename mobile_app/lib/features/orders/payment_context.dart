/// Тип оплаты в форме заявки: чьи условия грузить и когда выбор уходит на сервер.
///
/// Регрессия 19.11.2026: форма слала статичное «По факту» для юрлица с
/// отгрузкой в долг, и заявка вставала в «ждём оплату». Теперь тип оплаты
/// отправляется, только если варианты загружены именно для этих клиента и
/// организации; иначе его выбирает сервер (кредит → «в долг»).
/// Зеркало веб-функций `paymentOptionsClientId` / `paymentCtxKey` /
/// `paymentRadiosMatch` (frontend/index.html, @pure:payment-ctx).
library;

/// Чьи коммерческие условия запрашивать. null — грузить нечего (клиент не выбран,
/// разовый клиент — физлицо, «без клиента» без организации).
String? paymentOptionsClientId({
  required bool isStaff,
  required String userId,
  String? selectedClientId,
  String? organizationId,
  required String noClientMarker,
  required String oneOffMarker,
}) {
  if (!isStaff) return userId;
  if (selectedClientId == null || selectedClientId == oneOffMarker) return null;
  // «Без клиента» — условия организации через самого сотрудника.
  if (selectedClientId == noClientMarker) {
    return organizationId == null ? null : userId;
  }
  return selectedClientId;
}

String? paymentCtxKey(String? clientId, String? organizationId) =>
    clientId == null ? null : '$clientId|${organizationId ?? ''}';

/// Отправлять ли выбранный тип оплаты: варианты загружены для текущего контекста.
bool paymentRadiosMatch(String? renderedKey, String? expectedKey) =>
    expectedKey != null && renderedKey == expectedKey;

/// Тип оплаты по умолчанию: юрлицо с кредитом — «в долг», иначе первый доступный.
String defaultPaymentType({
  required List<String> types,
  required bool creditAllowed,
}) {
  if (creditAllowed && types.contains('debt')) return 'debt';
  return types.isEmpty ? 'on_delivery' : types.first;
}
