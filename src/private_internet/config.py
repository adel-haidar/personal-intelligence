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
    app_domain: str = "adel-intelligence.com"

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

    upload_dir: str = "/uploads"

    # ── Billing (Stripe) ────────────────────────────────────────
    # Master switch. While False the app is NOT gated on a subscription, so the
    # current deployment and existing users are unaffected until keys are set.
    billing_enabled: bool = False
    stripe_secret_key: str = ""        # sk_test_… / sk_live_…
    stripe_webhook_secret: str = ""    # whsec_… (from the webhook endpoint)
    stripe_price_id: str = ""          # price_… (the recurring Price to subscribe to)
    stripe_trial_days: int = 0         # 0 = no trial; >0 = card-required free trial

    @property
    def base_url(self) -> str:
        return f"https://{self.app_domain}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
