# BaltOIL Mobile — Build Guide

## Prerequisites

- Flutter SDK **3.38.4 or later** (Dart 3.11.5+)
- Android SDK with build-tools (installed via Android Studio or `sdkmanager`)
- A signing keystore (or use the debug key for internal testing — see below)
- `adb` on PATH if installing via USB

Check your Flutter version:
```
flutter --version
```

---

## Release APK against production backend

### 1. Install dependencies
```
cd mobile_app
flutter pub get
```

### 2. Build the release APK
```
flutter build apk --release
```

**No `--dart-define` is required.** The defaults in `lib/core/app_config.dart`
already point at production (`crm.9171517.ru`) through the single TLS gateway
on port **443**, mirroring the web frontend:

| Service       | Base URL                                        |
|---------------|-------------------------------------------------|
| Auth          | `https://crm.9171517.ru/api/auth/api/v1`         |
| Orders        | `https://crm.9171517.ru/api/order/api/v1`        |
| Delivery      | `https://crm.9171517.ru/api/delivery/api/v1`     |
| Chat (+ WS)   | `https://crm.9171517.ru/api/chat` / `wss://…`    |
| Notifications | `https://crm.9171517.ru/api/notif/api/v1`        |
| Calls         | `https://crm.9171517.ru/api/call`                |

> **Do not build against ports 8001–8006.** They are open on the server, but
> many ISPs and mobile carriers drop non-standard ports, so the app times out on
> a real phone. That was the cause of the "app does not connect" report on
> 1.1.1+3. Port 443 always gets through and carries a valid Let's Encrypt cert.

To point at a different host (staging), pass `--dart-define=API_HOST=<host>` —
the gateway path prefixes stay the same.

### 3. Find the APK
```
build/app/outputs/flutter-apk/app-release.apk
```

### 4. Install on device
Via USB (device must have USB debugging enabled):
```
adb install -r build/app/outputs/flutter-apk/app-release.apk
```

Or copy the APK to the device and open it in the Files app.

---

## Signing

Release builds are signed with the real keystore. `android/key.properties` is
gitignored and must exist on the build machine:

```properties
storePassword=<see D:/BaltOIL/_keys/sztk-release-keystore-password.txt>
keyPassword=<same>
keyAlias=sztk
storeFile=D:/BaltOIL/_keys/sztk-release.jks
```

Without `key.properties` the release build falls back to the debug key — such an
APK will **not** install over an existing release install on users' devices.

---

## Firebase / Push Notifications

The repo does **not** contain `google-services.json` (it is gitignored). This is intentional —
Firebase config contains project credentials and must not be committed.

**Without `google-services.json` the app still builds and runs.** `Firebase.initializeApp()`
will throw at startup, which `push/push_registrar.dart` catches silently. The app works
fully without push notifications; users see notifications on the in-app Notifications screen.

**To enable push notifications:**
1. Create a Firebase project and register the Android app with package ID `ru.baltoil.baltoil_mobile`.
2. Download `google-services.json` and place it at `android/app/google-services.json`.
3. Add the google-services Gradle plugin to `android/app/build.gradle.kts`:
   ```kotlin
   id("com.google.gms.google-services")
   ```
   And to `android/settings.gradle.kts` plugin block:
   ```kotlin
   id("com.google.gms.google-services") version "4.4.2" apply false
   ```
4. Rebuild.

---

## Dev/Test Login Credentials

See `DEV_SETUP.md` in the repo root for seed credentials (admin, manager, driver, client).

---

## Blockers / Prerequisites for Physical-Device Test

| Item | Status |
|------|--------|
| Prod server must accept inbound TCP on **8001, 8002, 8005** from the device's network | Must verify with DevOps/firewall |
| Device needs internet access to `<PROD_HOST>` | Required |
| Valid TLS certificate on prod nginx (ports 8001/8002/8005) | Required; if self-signed, build with `--dart-define=ALLOW_BAD_CERTS=true` in debug mode |
| `google-services.json` | Optional — push is disabled gracefully without it |
| `adb` or manual APK copy | For installation |

---

## Local emulator (Android Studio)

For local development against a backend running on the host machine, switch to
direct service ports (no nginx gateway on a bare local stand):
```
flutter run \
  --dart-define=API_HOST=10.0.2.2 \
  --dart-define=API_DIRECT_PORTS=true \
  --dart-define=ALLOW_BAD_CERTS=true
```
`10.0.2.2` is the Android emulator's loopback alias for the host. Physical devices
must use the host's actual LAN IP or the prod hostname.

---

## Notes / Gotchas

- **`ALLOW_BAD_CERTS` in release mode**: The bad-certificate bypass is always disabled
  in `--release` builds regardless of the dart-define value (guarded by `!kReleaseMode`
  in `core/api_client.dart`). Passing `ALLOW_BAD_CERTS=true` in a `--release` build
  has no effect.
- **`flutter.minSdkVersion`**: Defaults to API 21 (Android 5.0). The app uses
  `flutter_secure_storage` which requires API 18+, so API 21 is safe. Lower values
  are not supported.
- **Refresh token flow**: On 401, the API client automatically attempts a token refresh
  (`POST /api/v1/auth/refresh`). If that also fails, the user is routed back to the
  login screen.
- **Driver orders screen**: The backend returns all orders the driver can see
  (their own accepted orders + free `new` orders). Splitting into sections happens
  client-side. If a driver's ID is not found in any order's `driver_id`, the "In work"
  section will be empty — this is expected after claim.
- **Gradle JVM heap**: `android/gradle.properties` sets `-Xmx8G`. On machines with
  less than 8 GB free, reduce to `-Xmx4G`.
