/// Кто и что может править в заявке — зеркало веба (`canEditOrderFields`,
/// `_editPencil`, `_editPencilStaff`, `_canEditContactOf`) и бэкенда
/// (`order_service._check_edit_permissions`, `_check_closed_order_edit`).
/// Последнее слово всегда за бэкендом — здесь только решаем, рисовать ли
/// карандаш. Чистые функции без Flutter — покрыты unit-тестами.
library;

/// Статусы, в которых заявку ещё правят все, кому она доступна.
const kOpenOrderStatuses = {'new', 'awaiting_manager', 'accepted'};

/// Закрытые статусы (CRM-39): доставленную/отменённую правит только админ.
const kClosedOrderStatuses = {'delivered', 'cancelled'};

/// Объём и топливо закрытой заявки не меняются: по ним уже выписаны ТТН
/// и счёт, списан склад.
const kFrozenInClosed = {'fuel_type', 'volume_requested'};

/// Поля, которые правят только менеджер и админ (веб `_editPencilStaff`).
const kStaffOnlyFields = {
  'organization_id',
  'delivery_cost',
  'fuel_cost',
};

/// Контакт приёмки и комментарии (CRM-45): их правит и водитель —
/// он узнаёт эти данные на объекте первым.
const kContactFields = {
  'contact_person_name',
  'contact_person_phone',
  'client_comment',
  'manager_comment',
};

bool _isStaffRole(String role) => role == 'manager' || role == 'admin';

/// Может ли пользователь вообще править поля этой заявки (веб
/// `canEditOrderFields`).
bool canEditOrderFields({
  required String role,
  required String userId,
  required String status,
  String? clientId,
  String? driverId,
}) {
  switch (role) {
    case 'admin':
      return kOpenOrderStatuses.contains(status) ||
          kClosedOrderStatuses.contains(status);
    case 'manager':
      return kOpenOrderStatuses.contains(status);
    case 'client':
      return clientId == userId && kOpenOrderStatuses.contains(status);
    case 'driver':
      return driverId == userId && (status == 'new' || status == 'accepted');
  }
  return false;
}

/// Рисовать ли карандаш у поля [field].
bool canEditOrderField(
  String field, {
  required String role,
  required String userId,
  required String status,
  String? clientId,
  String? driverId,
}) {
  final base = canEditOrderFields(
    role: role,
    userId: userId,
    status: status,
    clientId: clientId,
    driverId: driverId,
  );
  if (!base) return false;
  if (kFrozenInClosed.contains(field) &&
      kClosedOrderStatuses.contains(status)) {
    return false;
  }
  if (kStaffOnlyFields.contains(field)) return _isStaffRole(role);
  if (kContactFields.contains(field)) {
    // Внутренний комментарий клиенту не виден и не правится (CRM-41).
    return _isStaffRole(role) || role == 'driver';
  }
  return true;
}

/// Ставка НДС, которую кнопка «Добавить НДС» начисляет на доставку.
const kDeliveryVatPercent = 22;

/// «Добавить НДС» к ручной стоимости доставки (правки 2026-09-28): одноразово
/// ×1,22 с округлением до копейки (3 500 → 4 270). Флаг в заявке не хранится —
/// поэтому кнопка гаснет до ручной правки поля. `null` — умножать нечего.
double? withDeliveryVat(String raw) {
  final v = double.tryParse(raw.trim().replaceAll(',', '.'));
  if (v == null || !v.isFinite || v <= 0) return null;
  // Считаем в копейках, чтобы не ловить хвосты double.
  final cents = (v * 100).round();
  return (cents * (100 + kDeliveryVatPercent) / 100).round() / 100;
}

/// Сумма для поля ввода: целые рубли без «.0», иначе копейки.
String formatDeliveryCostInput(double v) =>
    v == v.roundToDouble() ? v.toStringAsFixed(0) : v.toStringAsFixed(2);
