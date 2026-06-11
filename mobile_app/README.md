# БалтОйл — мобильное приложение (Flutter)

Тонкий клиент к существующему бэкенду: вся бизнес-логика на сервере,
приложение дёргает те же REST-ручки, что и веб.

## Структура

```
lib/
├── main.dart                 # вход, выбор стартового экрана по наличию сессии
├── core/
│   ├── app_config.dart       # хосты/порты сервисов (--dart-define=API_HOST=...)
│   ├── api_client.dart       # Dio + Bearer + авто-refresh на 401
│   └── token_storage.dart    # JWT-пара в Keystore/Keychain
├── features/
│   ├── auth/                 # вход: пароль и SMS-код (login_screen, auth_repository)
│   ├── home/                 # каркас с нижней навигацией
│   ├── orders/               # список заявок, создание заявки
│   └── notifications/        # экран уведомлений (read/read-all)
└── push/
    └── push_registrar.dart   # FCM-токен → POST /api/v1/devices (no-op без Firebase)
```

## Запуск (локальная разработка)

Бэкенд поднят docker-compose'ом на хосте. Из Android-эмулятора хост виден
как `10.0.2.2` — это дефолт, поэтому просто:

```
flutter run
```

Реальное устройство / прод:

```
flutter run --dart-define=API_HOST=<хост-бэка>
```

Самоподписанный TLS-сертификат принимается только в debug-сборке
(`AppConfig.allowBadCertificates`); в release проверка сертификата всегда
строгая — на проде нужен нормальный сертификат (Let's Encrypt).

## Push-уведомления (FCM) — что нужно для включения

Приложение и бэкенд уже готовы; пуши молчат, пока не подключён Firebase.

1. Создать проект в Firebase Console, добавить Android-приложение
   `ru.baltoil.baltoil_mobile`, скачать `google-services.json`
   в `android/app/`.
2. Подключить gradle-плагин google-services:
   - `android/settings.gradle.kts` → plugins:
     `id("com.google.gms.google-services") version "4.4.2" apply false`
   - `android/app/build.gradle.kts` → plugins:
     `id("com.google.gms.google-services")`
3. В Firebase Console → Project Settings → Service accounts →
   сгенерировать ключ сервис-аккаунта (JSON) для бэка.
4. На сервере: положить JSON рядом с notification_service, смонтировать
   в контейнер и прописать в `notification_service/.env`:
   ```
   FCM_CREDENTIALS_FILE=/app/fcm-service-account.json
   PUSH_ENABLED=true
   ```
   В docker-compose.yml для notification_service добавить volume:
   ```
   - ./secrets/fcm-service-account.json:/app/fcm-service-account.json:ro
   ```
5. iOS (позже): добавить приложение в тот же Firebase-проект, загрузить
   APNs-ключ в Firebase, `GoogleService-Info.plist` в Runner.

Без этих шагов приложение работает полностью, кроме фоновых пушей —
уведомления видны на вкладке «Уведомления».

## Бэкенд-ручки, которые использует приложение

| Действие | Ручка |
|---|---|
| Вход по паролю | `POST :8001/api/v1/auth/login` |
| Вход по SMS | `POST :8001/api/v1/auth/login/request-code` → `/verify-code` |
| Обновление токена | `POST :8001/api/v1/auth/refresh` |
| Профиль | `GET :8001/api/v1/auth/me` |
| Заявки | `GET/POST :8002/api/v1/orders` |
| Топливо в наличии | `GET :8002/api/v1/fuel-types` |
| Уведомления | `GET :8005/api/v1/notifications`, `POST .../read`, `/read-all` |
| Регистрация устройства | `POST :8005/api/v1/devices`, `DELETE .../{token}` |
