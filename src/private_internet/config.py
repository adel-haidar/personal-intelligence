from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",  # silently ignores vars not defined as fields
    )

    # ── Branding / deployment ───────────────────────────────────
    app_name: str = "Private Internet"
    # Public domain the platform is served from. Default keeps the current
    # production deployment working; self-hosters set APP_DOMAIN in .env.
    app_domain: str = "app.private-internet.io"

    # ── Multi-user platform ─────────────────────────────────────
    seed_admin_email: str = ""        # existing single-user data is assigned to this user
    registration_open: bool = True    # False → invite-only (CLI-created accounts)
    max_users: int = 100              # 0 = unlimited

    # Email verification. Default False so the current register→token flow keeps
    # working until SES (a later phase) lands. Flip to True to gate login on a
    # verified email and switch register to a "verification sent" response.
    require_email_verification: bool = False
    verification_token_ttl_hours: int = 24
    reset_token_ttl_hours: int = 1
    # Per-IP registration throttle (abuse mitigation). Generous by default so an
    # admin creating several test/family accounts from one IP isn't blocked.
    register_rate_limit_per_hour: int = 20

    db_host: str = "localhost"
    db_name: str = "postgres"
    db_user: str = "postgres"
    db_password: str = ""

    secret_key: str = ""
    dashboard_password: str = ""

    aws_region: str = "eu-central-1"

    # ── Transactional email (SES) ───────────────────────────────
    # "log" (default) just logs the actionable link at INFO — deploying without
    # SES configured changes nothing. "ses" sends via AWS SESv2 (only when
    # ses_sender_email is also set). ses_sender_email must be a verified SES
    # identity; ses_configuration_set is passed only when non-empty.
    email_backend: str = "log"          # "log" | "ses"
    ses_sender_email: str = ""          # e.g. "no-reply@private-internet.io"
    ses_configuration_set: str = ""     # optional SES configuration set name

    # ── Brain embeddings (self-hosted, Bedrock-free path) ───────
    # The brain owns its embedding model so the memory store can run on any host
    # (AWS now, user-owned hardware later). "bedrock" keeps the legacy Amazon
    # Titan v2 path; "ollama" uses a local Ollama server. Both emit 1024-d
    # vectors, so the memories.embedding vector(1024) column is unchanged.
    # Flip to "ollama" only AFTER re-embedding existing rows
    # (scripts/reembed_memories.py) — bge-m3 vectors are not comparable to Titan
    # vectors, so querying one against the other returns meaningless results.
    embedding_backend: str = "bedrock"            # "bedrock" | "ollama"
    embedding_url: str = "http://127.0.0.1:11434"  # Ollama server (localhost)
    embedding_model: str = "bge-m3"                # Ollama model tag, 1024-d

    # ── Image generation (fal.ai) ───────────────────────────────
    # Bedrock's image models (Nova Canvas, Titan G2) are EOL'd/legacy-revoked in
    # this account, so SIGNAL slides + PULSE post images fall back to gradients.
    # fal.ai FLUX is the active backend (cheap: schnell ~$0.003/image). On any
    # failure (incl. unfunded balance) the pipeline still falls back to a gradient.
    image_backend: str = "fal"                     # "fal" | "bedrock"
    fal_api_key: str = ""
    fal_image_model: str = "fal-ai/flux/schnell"   # cheap/fast distilled FLUX

    # ── SIGNAL narration (ElevenLabs TTS) ───────────────────────
    # "elevenlabs" uses ElevenLabs (multilingual, natural); falls back to Polly
    # when the engine is "polly" OR no ELEVENLABS_API_KEY is set, so deploys are safe.
    tts_engine: str = "elevenlabs"                 # "elevenlabs" | "polly"
    elevenlabs_api_key: str = ""
    elevenlabs_model_id: str = "eleven_multilingual_v2"

    # ── SIGNAL video (fal.ai, Kling) ────────────────────────────
    # "fal" generates a real video clip per section; "slides" keeps the legacy
    # still-image + Ken Burns. Any fal failure (incl. unfunded balance) falls back
    # to a slide per section, so the video always assembles.
    video_backend: str = "fal"                     # "fal" | "slides"
    fal_video_model: str = "fal-ai/kling-video/v1/standard/text-to-video"
    # Clip durations (seconds) the configured fal_video_model accepts. The fal
    # call snaps each requested per-scene duration to the nearest value here.
    # Kling v1 standard = "5,10"; set "5,8,10" for models that also support 8s
    # (e.g. Veo3). Comma-separated so it is overridable per-instance via env.
    fal_video_durations: str = "5,10"

    # ── SIGNAL/PULSE video (Wan2.1 via Replicate) ───────────────
    # Video clips are routed by content type in content/video_provider.py:
    # SIGNAL + PULSE use Wan2.1 on Replicate (high volume, cost-efficient 720p);
    # STORIES stays on Kling (fal, above). Key comes from the environment only.
    #
    # A failed SIGNAL/PULSE clip degrades through the fallback hierarchy:
    #   1. Wan2.1 (Replicate) — primary
    #   2. Image-slide (fal FLUX + Ken Burns FFmpeg) — motion without video model
    #   3. Colour card — last resort
    # A failed SIGNAL/PULSE clip must NEVER trigger a Kling call (cost model).
    replicate_api_key: str = ""
    # Verified Replicate model slug. wavespeedai/wan-2.1-t2v-720p is the
    # accelerated 720p variant with configurable duration (num_frames + fps).
    # Replaces wan-video/wan-2.1-1.3b which produced fixed ~5s 480p clips with
    # no duration control. Pricing: ~$0.07/second of output video.
    # fal.ai was evaluated (2026-06-17) but has no publicly documented WAN model
    # with verifiable input fields; Replicate is kept as the WAN provider.
    wan2_model: str = "wavespeedai/wan-2.1-t2v-720p"
    # Supported target durations (seconds) for the WAN model. The client picks
    # (num_frames, fps) pairs that land on these values given the model's
    # num_frames range 81–100 and fps range 5–24. Comma-separated so it is
    # overridable per instance. The default set covers typical SIGNAL scene
    # lengths. See replicate_wan_client._DURATION_PARAMS for the exact pairs.
    wan2_durations: str = "5,6,8,10,16"

    upload_dir: str = "/uploads"

    # ── ARIA music (ElevenLabs music generation) ────────────────
    # aria_music_enabled: master switch. When False, the generator is a no-op
    # (returns immediately) so the module can be deployed before billing/keys land.
    # elevenlabs_api_key is shared with SIGNAL narration above.
    aria_music_enabled: bool = True
    # "suno" uses Suno AI (sunoapi.org) for full-length 2–4 min tracks (current
    # provider). "elevenlabs" is the legacy /v1/music path (now used only by the
    # podcast generator). ARIA's generator uses Suno regardless of this value.
    aria_music_backend: str = "suno"
    # Number of waveform bars to compute per track.
    aria_waveform_bars: int = 200

    # ── ARIA music (Suno AI — sunoapi.org) ──────────────────────
    # Suno generates complete songs (2–4 min). Key comes from the environment
    # only (SUNO_API_KEY) — never hardcode or read it from a secrets file.
    suno_api_key: str = ""
    suno_base_url: str = "https://api.sunoapi.org"
    # Model version: V4 | V4_5 | V4_5PLUS | V4_5ALL | V5 | V5_5. V4_5 reliably
    # produces 2–4 min tracks (well over the 120s ARIA minimum).
    suno_model: str = "V4_5"
    # Suno requires a callBackUrl on every generate request. We poll
    # record-info instead of consuming callbacks (polling is authoritative), so
    # this only needs to be a reachable https URL. Defaults to our own domain.
    suno_callback_url: str = ""

    # ── Billing (Stripe) ────────────────────────────────────────
    # Master switch. While False the app is NOT gated on a subscription, so the
    # current deployment and existing users are unaffected until keys are set.
    billing_enabled: bool = False
    stripe_secret_key: str = ""        # sk_test_… / sk_live_…
    stripe_webhook_secret: str = ""    # whsec_… (from the webhook endpoint)
    # Legacy single-tier price; still honoured as the "pro" price when
    # stripe_price_pro is unset, so old configs keep working.
    stripe_price_id: str = ""          # price_… (recurring Price)
    # Per-tier recurring prices (Free has no price). Set these to enable the
    # Pro/Max checkout flows.
    stripe_price_pro: str = ""         # price_… for the Pro tier
    stripe_price_max: str = ""         # price_… for the Max tier
    stripe_trial_days: int = 0         # 0 = no trial; >0 = card-required free trial
    # Tester / early-adopter access codes. Comma-separated list seeded at startup
    # as multi-use coupons granting the Max plan for 30 days (no card, no Stripe).
    # e.g. TESTER_COUPONS="EARLYBIRD,FRIENDS2026". Empty → no seeded codes.
    tester_coupons: str = ""

    # ── Social login (Google OAuth) ─────────────────────────────
    # Inert until BOTH are set: the dashboard "Continue with Google" button then
    # issues a platform JWT. Separate from the OAuth 2.1 server in auth/.
    # Redirect URI to register in Google Cloud: {base_url}/api/auth/google/callback
    # Also reused by the Google Drive connector (connectors/providers/gdrive.py).
    # Register an additional redirect URI: {base_url}/api/connectors/gdrive/callback
    google_client_id: str = ""
    google_client_secret: str = ""

    # ── Connectors (external platform import) ───────────────────
    # Each connector is inert until its client_id + client_secret are both set.
    # Notion: register redirect URI {base_url}/api/connectors/notion/callback
    notion_client_id: str = ""
    notion_client_secret: str = ""
    # GitHub: register redirect URI {base_url}/api/connectors/github/callback
    github_client_id: str = ""
    github_client_secret: str = ""

    @property
    def base_url(self) -> str:
        return f"https://{self.app_domain}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
