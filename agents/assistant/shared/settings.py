from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All configuration values for the application.

    Pydantic reads these automatically from environment variables (or a .env file).
    The variable names map directly to the field names in uppercase, e.g.
    the field `rapidapi_key` is read from the environment variable `RAPIDAPI_KEY`.

    Fields without a default value are required — the app will refuse to start
    if they are missing.
    """

    # The .env is SHARED with Service A (and carries keys this service doesn't
    # use — e.g. the deactivated email assistant's ms_* credentials, Stripe,
    # Google IdP). Ignore unknown keys instead of the pydantic-settings default
    # of forbidding them, otherwise every agents request 500s on Settings
    # validation when a new key is added to the shared .env.
    model_config = {"env_file": ".env", "extra": "ignore"}

    aws_region: str = "eu-central-1"
    """The AWS region where the Bedrock model is available."""

    bedrock_model_id: str = "eu.amazon.nova-2-lite-v1:0"
    """The Amazon Bedrock model ID used for the agents' LLM inference."""

    user_name: str = ""
    """The name of the user the assistant is working for. Used in LLM prompts.

    Defaults to empty string — callers that inject this into prompts must handle the
    empty case gracefully (e.g. omit "Hello, <name>" or fall back to "the user").
    Set USER_NAME in the environment to override for a single-tenant deployment."""

    # Shared HS256 secret with Service A (same .env) — lets the agents verify
    # platform JWTs issued by the dashboard login.
    secret_key: str = ""

    mcp_memory_url: str | None = None
    """The SSE endpoint of the MCP memory server, e.g. 'http://ec2-ip:3000/sse'.
    When set, the agents query this server for personal context. Leave unset to
    disable memory lookups."""

    mcp_memory_client_id: str | None = None

    mcp_memory_refresh_token: str | None = None

    internal_secret: str | None = None
    """Shared secret for same-host service auth to the memory API (read from
    INTERNAL_SECRET). Sent to Service A, which resolves it to the seed admin —
    replaces the fragile OAuth refresh-token dance. Stable, no expiry."""

    # Job hunting agent
    database_url: str | None = None
    """PostgreSQL DSN for the job_matches table, e.g. postgresql://user:pass@localhost/adel_intelligence.
    If not set directly, assembled from DB_HOST / DB_USER / DB_PASSWORD / DB_NAME / DB_PORT."""

    # Individual DB connection components — read from DB_HOST, DB_USER, etc.
    # Used to assemble database_url when it is not provided as a full DSN.
    db_host: str | None = None
    db_user: str | None = None
    db_password: str | None = None
    db_name: str = "postgres"
    db_port: int = 5432

    @model_validator(mode="after")
    def assemble_database_url(self) -> "Settings":
        if self.database_url is None and all(
            [self.db_host, self.db_user, self.db_password]
        ):
            self.database_url = (
                f"postgresql://{self.db_user}:{self.db_password}"
                f"@{self.db_host}:{self.db_port}/{self.db_name}"
            )
        return self

    rapidapi_key: str | None = None
    """RapidAPI key for the JSearch / LinkedIn Jobs Search API."""

    rapidapi_host: str = "jsearch.p.rapidapi.com"
    """RapidAPI host header — override to 'linkedin-jobs-search.p.rapidapi.com' if using that API."""

    scraper_delay_seconds: float = 2.0
    """Seconds to wait between page requests to avoid rate-limiting."""

    scraper_max_results_per_query: int = 20
    """Maximum job listings to collect per search query."""

    job_score_concurrency: int = 6
    """How many job listings to score with Bedrock in parallel. The per-listing
    LLM call dominates a run's wall time; raising this shortens runs but risks
    Bedrock throttling. Lower it if you see ThrottlingException in the logs."""


@lru_cache
def get_settings() -> Settings:
    """Return the application settings, reading from environment variables once and caching the result.

    The `@lru_cache` decorator means this function only does the actual work on
    the first call. Every subsequent call returns the same cached object instantly,
    so environment variables are only read once at startup.
    """
    return Settings()
