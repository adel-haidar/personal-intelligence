/// Canonical list of backend endpoints. The base URL is defined ONCE here and
/// nowhere else (per project constraints — no hardcoded URLs in feature code).
///
/// All paths are verified against the live FastAPI backend:
/// * Service A (port 8000, public via nginx `/api/`): auth, memory, content,
///   brain, billing.
/// * Service B (port 8001, public via nginx `/api/health/`, `/api/banking/`,
///   `/api/investing/`, `/api/trading/`): health + finance.
///
/// Paths that the task spec assumed but that DO NOT exist on the backend are
/// noted as `// MISSING` — the matching UI degrades gracefully.
class ApiEndpoints {
  ApiEndpoints._();

  /// The single source of truth for the API origin.
  static const String baseUrl = 'https://adel-intelligence.com/api';

  /// Custom scheme used for the cloud-wearable OAuth deep link.
  static const String oauthCallbackScheme = 'adel-intelligence';

  // ---- Auth (Service A, prefix /api/auth) -------------------------------
  static const String register = '/auth/register';
  static const String login = '/auth/login';
  static const String me = '/auth/me';
  static const String profile = '/auth/profile';
  static const String avatar = '/auth/avatar';
  static const String notifications = '/auth/notifications';
  static const String resendVerification = '/auth/resend-verification';
  static const String forgotPassword = '/auth/forgot-password';
  static const String onboarding = '/auth/onboarding';
  static const String exportData = '/auth/export';
  static const String clearBrain = '/auth/clear-brain';
  static const String deleteAccount = '/auth/account';
  // MISSING: there is no `/auth/refresh`. Tokens are single 7-day JWTs.

  // ---- Memory / brain (Service A, prefix /api) --------------------------
  static const String memoryText = '/memory/text';
  static const String memory = '/memory';
  static const String memorySearch = '/memory/search';
  static const String memoryStats = '/memory/stats';
  static String memoryById(String id) => '/memory/$id';
  static const String fileUpload = '/file';

  static const String brainOrganise = '/brain/organise';
  static const String brainOrganiseStatus = '/brain/organise/status';

  // ---- Content: PULSE + SIGNAL (Service A, prefix /api/content) ---------
  static const String creators = '/content/creators';
  static const String posts = '/content/posts';
  static const String videos = '/content/videos';
  static const String interactions = '/content/interactions';
  static const String topics = '/content/topics';

  // ---- STORIES (Service A, prefix /api/stories) -------------------------
  static const String stories = '/stories';
  static const String storiesCategories = '/stories/categories';
  static const String storiesSearch = '/stories/search';
  static const String storiesProgress = '/stories/progress';
  static const String storiesLike = '/stories/like';
  static String storyFilm(String id) => '/stories/films/$id';
  static String storySeries(String id) => '/stories/series/$id';
  static String storySeriesEpisodes(String id) => '/stories/series/$id/episodes';

  // ---- ARIA (Service A, prefix /api/aria) -------------------------------
  static const String ariaLibrary = '/aria/library';
  static const String ariaSearch = '/aria/search';
  static const String ariaPlay = '/aria/play';
  static const String ariaPlayEnd = '/aria/play-end';
  static const String ariaLike = '/aria/like';
  static const String ariaQueueNext = '/aria/queue/next';
  static String ariaTrack(String id) => '/aria/tracks/$id';
  static String ariaPlaylist(String id) => '/aria/playlists/$id';

  // ---- Billing (Service A, prefix /api/billing) -------------------------
  static const String billingStatus = '/billing/status';
  static const String billingCheckout = '/billing/checkout';
  static const String billingPortal = '/billing/portal';

  // ---- Health (Service B, public via /api/health) -----------------------
  static const String healthManualEntry = '/health/manual-entry';
  static const String healthImportAppleHealth = '/health/import/apple-health';
  static const String healthTrends = '/health/trends';
  static String healthDaily(String date) => '/health/daily/$date';
  static String healthSummary(String date) => '/health/summary/$date';
  static String healthRunDaily(String date) => '/health/run-daily/$date';
  // MISSING: `/health/devices/*/connect`, `/health/sync-status`. Device OAuth +
  // live-sync are surfaced as "coming soon" in the UI.

  // ---- Finance (Service B) ----------------------------------------------
  static const String bankingAnalyse = '/banking/analyse';
  static const String bankingLatest = '/banking/analysis/latest';
  static const String investingLatest = '/investing/latest';
  static const String tradingLatest = '/trading/latest';
  // MISSING: `/finances/upload`. Statement upload reuses `/file` (indexed to brain).
}
