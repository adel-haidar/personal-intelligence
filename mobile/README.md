# Private Internet — Mobile (Flutter)

A full-featured mobile client for the **Private Internet** platform (repo dir
`personal-intelligence`). It talks **only** to the existing FastAPI backend at
`https://adel-intelligence.com/api/*` — there is no new backend.

- **Design system:** Calm Intelligence (matches the Vue web frontend).
- **State:** Riverpod (manual API — see [Codegen note](#codegen-note)).
- **Targets:** iOS 16+, Android 10+ (API 29+).
- **Toolchain:** Flutter **3.27+ / Dart 3.6+** (uses `Color.withValues` and
  `TextScaler.clamp`).

---

## 1. First-time setup

This package ships the Dart app (`lib/`), `pubspec.yaml` and `analysis_options.yaml`.
The native iOS/Android shells are **not** checked in — generate them once, then
apply the [platform overrides](#5-platform-configuration) below.

```bash
cd mobile

# Generate the ios/ and android/ native projects in place.
flutter create --platforms=ios,android --org com.adel.privateinternet .

flutter pub get
flutter analyze        # must pass clean
flutter run            # on a connected device / simulator
```

> `flutter create .` will not overwrite existing Dart files. After it runs,
> edit the generated `Info.plist` / `AndroidManifest.xml` / `build.gradle` with
> the entries in section 5.

---

## 2. Project structure

```
lib/
├── core/
│   ├── theme/      app_colors, app_text_styles, app_theme, app_dimens
│   ├── api/        api_client (Dio), api_endpoints, api_exception
│   ├── auth/       token_storage (secure), auth_repository
│   ├── health/     health_bg_sync_service (Open Wearables stub)
│   ├── models/     plain immutable models + json_utils (no codegen)
│   ├── utils/      format helpers
│   ├── widgets/    brain_pulse, app_card/button/input, tone_pill,
│   │               score_badge, progress_bar, insight_card, upload_banner,
│   │               device_connection_card, toast, states (shimmer/empty/error)
│   └── router/     app_router (GoRouter + auth guard + deep links)
├── features/       auth, onboarding, dashboard, brain, pulse, signal,
│                   health, finances, settings, shell
├── providers/      core, auth, theme, brain, pulse, signal, health,
│                   finances, dashboard
└── main.dart
```

---

## 3. How it maps to the real backend

The app was built against the **actual** routes (verified in
`src/private_internet/*` and `agents/assistant/health`). Some endpoints the
original spec assumed **do not exist**; those flows degrade gracefully. All
paths live in `lib/core/api/api_endpoints.dart`.

| Area | Real endpoint(s) | Notes |
|------|------------------|-------|
| Auth | `POST /api/auth/login` → `{token, user}`, `register`, `me`, `profile`, `avatar`, `export`, `clear-brain`, `account`, `onboarding` | **Single 7-day JWT, no refresh token.** On a 401 the app clears the session and returns to login. |
| Brain | `/api/memory/text\|/memory\|/memory/search\|/memory/stats\|/memory/{id}`, `/api/file`, `/api/brain/organise(/status)` | Memory search is `/memory/search` (not `/memories/search`). |
| Pulse / Signal | `/api/content/posts\|videos\|creators\|topics\|interactions` | SIGNAL "processing" is polled by re-fetching `/videos` (no `/signal/status`). |
| Health | `/api/health/daily/{date}`, `/summary/{date}`, `/trends`, `/run-daily/{date}`, `/manual-entry` | Served by the agents service (8001) via nginx. |
| Finances | `/api/banking/analysis/latest` (+ investing/trading) | Statement upload reuses `/api/file` (no `/finances/upload`). |

### Known backend gaps (surfaced as "coming soon" / graceful states)

- **Wearable device OAuth + live sync** — there is no `/health/devices/*/connect`
  or `/health/sync-status`. Device cards show *Coming soon*; the OAuth deep-link
  route + `HealthCallbackScreen` are wired and ready for when the backend lands.
- **Token refresh** — none exists; sessions are 7-day JWTs.
- **Dedicated finances upload / health-data delete** — reuse `/api/file` and
  Settings → *Clear my brain* respectively.

---

## 4. Codegen note

The spec called for `freezed` + `json_serializable` + `riverpod_generator`.
Because this package is delivered without a `build_runner` step, the code
instead uses **hand-written immutable models** (`lib/core/models/`, with
defensive parsing in `json_utils.dart`) and the **manual Riverpod API**
(`NotifierProvider` / `AsyncNotifierProvider`). This compiles immediately after
`flutter pub get` with no generated files. `riverpod_annotation` is kept in
`pubspec.yaml` to ease a later migration to `@riverpod` if desired.

---

## 5. Platform configuration

Apply these after `flutter create .`.

### iOS — `ios/Runner/Info.plist`

Add inside the top-level `<dict>`:

```xml
<!-- Health (Open Wearables / HealthKit background sync) -->
<key>NSHealthShareUsageDescription</key>
<string>Private Internet reads your health data to build your private insights.</string>
<key>NSHealthUpdateUsageDescription</key>
<string>Private Internet stores health data you choose to share on your own server.</string>

<!-- Background fetch for health sync -->
<key>BGTaskSchedulerPermittedIdentifiers</key>
<array>
  <string>com.adel.privateinternet.healthsync</string>
</array>

<!-- Avatar / document upload -->
<key>NSPhotoLibraryUsageDescription</key>
<string>Used to set your profile photo.</string>
<key>NSCameraUsageDescription</key>
<string>Used to take a profile photo.</string>

<!-- OAuth deep link for cloud wearables: adel-intelligence://health/callback -->
<key>CFBundleURLTypes</key>
<array>
  <dict>
    <key>CFBundleURLSchemes</key>
    <array><string>adel-intelligence</string></array>
  </dict>
</array>
```

Set the deployment target to **16.0** in `ios/Podfile`
(`platform :ios, '16.0'`) and in Xcode (Runner target → Minimum Deployments).

### Android — `android/app/src/main/AndroidManifest.xml`

```xml
<uses-permission android:name="android.permission.INTERNET"/>
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE"/>

<!-- Health Connect (Open Wearables). Add per metric you read: -->
<uses-permission android:name="android.permission.health.READ_HEART_RATE"/>
<uses-permission android:name="android.permission.health.READ_STEPS"/>
<uses-permission android:name="android.permission.health.READ_SLEEP"/>
<uses-permission android:name="android.permission.health.READ_WEIGHT"/>
<uses-permission android:name="android.permission.health.READ_OXYGEN_SATURATION"/>
<uses-permission android:name="android.permission.health.READ_EXERCISE"/>

<application android:usesCleartextTraffic="false" ...>
  <activity ...>
    <!-- OAuth deep link: adel-intelligence://health/callback -->
    <intent-filter android:autoVerify="false">
      <action android:name="android.intent.action.VIEW"/>
      <category android:name="android.intent.category.DEFAULT"/>
      <category android:name="android.intent.category.BROWSABLE"/>
      <data android:scheme="adel-intelligence" android:host="health"/>
    </intent-filter>
  </activity>
</application>
```

In `android/app/build.gradle`:

```gradle
android {
    compileSdk 34
    defaultConfig {
        minSdk 29
        targetSdk 34
    }
}
```

> **Deep-link routing:** GoRouter maps `https`/path links directly. The custom
> scheme `adel-intelligence://health/callback` (host `health`, path `/callback`)
> is captured by the intent filter / `CFBundleURLTypes`; route it to
> `/health/devices/callback` with `app_links` or `uni_links` when you enable
> cloud-device OAuth. The handler screen already exists
> (`features/health/health_callback_screen.dart`).

### Open Wearables SDK

`lib/core/health/health_bg_sync_service.dart` is a compile-safe **stub**
(`isAvailable == false`). To enable native background sync:

1. Add the dependency in `pubspec.yaml` (see the TODO there), e.g.
   ```yaml
   health_bg_sync:
     git: { url: https://github.com/<org>/open-wearables.git, path: packages/health_bg_sync }
   ```
2. Replace the stub bodies with the real `HealthBgSync.instance` calls (the
   intended call sequence is in the file's TODO comments).
3. The call site in the Health screen does not change.

---

## 6. Configuration knobs

- **API base URL** — `ApiEndpoints.baseUrl` (the single source of truth).
- **JWT** — stored in the OS keychain via `flutter_secure_storage`; never hardcoded.
- **Theme** — dark by default; persisted in `SharedPreferences`.

---

## 7. Repo / CI note

This lives in the `personal-intelligence` monorepo under `mobile/`. The backend
deploy workflow (`.github/workflows/deploy.yml`) triggers on **any** push to
`main` that isn't a `feat(dashboard)`/`fix(dashboard)` commit, so a mobile-only
push will currently run the backend deploy job. Add a `mobile/**` path filter to
the workflow (or use a dashboard-prefixed message) if you want mobile commits to
skip the prod backend redeploy.

---

## 8. Status / not-yet-done

- Native `ios/` & `android/` folders must be generated (`flutter create .`).
- `flutter analyze` / build were **not run in the authoring environment**
  (Flutter wasn't installed there). Run them after setup.
- Avatar image upload is wired to `image_picker` + `/api/auth/avatar` only where
  noted; verify multipart field names against your server build.
