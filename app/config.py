"""Application settings loaded from environment variables (prefix-free, see .env.example)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- general ---
    app_name: str = "newsforge"
    environment: str = "development"
    log_level: str = "INFO"
    log_json: bool = True
    api_key: str | None = Field(default=None, description="If set, required in X-API-Key for /api routes")
    cors_origins: list[str] = Field(default_factory=list, description='e.g. ["https://newsforge.example.com"]')

    # --- user accounts (Supabase Auth) ---
    # When set, the API accepts Supabase access tokens (Authorization: Bearer ...) and
    # authorizes people through the `members` table. API_KEY keeps working for automation.
    supabase_url: str | None = None
    supabase_jwt_audience: str = "authenticated"
    jwks_cache_seconds: int = 600
    # Emails that become admins on first sign-in (bootstraps the first admin).
    admin_emails: list[str] = Field(default_factory=list)

    # --- infrastructure ---
    database_url: str = "postgresql+asyncpg://crawler:crawler@localhost:5432/crawler"
    db_pool_size: int = 10
    db_echo: bool = False
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    celery_task_always_eager: bool = False
    scheduler_interval_seconds: int = 60

    # --- HTTP fetching ---
    user_agent: str = "NewsforgeBot/0.1 (+https://github.com/etisamhaq/Newsforge)"
    connect_timeout: float = 5.0
    read_timeout: float = 15.0
    total_timeout: float = 30.0
    max_response_bytes: int = 5 * 1024 * 1024
    max_sitemap_bytes: int = 50 * 1024 * 1024  # sitemap protocol allows up to 50 MB uncompressed
    max_redirects: int = 5
    max_retries: int = 3
    retry_backoff_base: float = 0.5
    retry_backoff_max: float = 30.0
    max_retry_after: float = 120.0
    default_min_delay: float = 1.0  # seconds between requests to the same host
    robots_cache_ttl: int = 3600
    respect_robots: bool = True
    allowed_ports: list[int] = [80, 443, 8080, 8443]
    allow_private_networks: bool = False  # NEVER enable in production

    # --- crawl limits ---
    default_max_pages: int = 200
    default_max_depth: int = 3
    max_url_length: int = 2048
    max_frontier_size: int = 5000
    crawl_time_budget_seconds: int = 1800
    crawl_concurrency: int = 4
    max_page_failures: int = 5  # skip URLs that failed this many times
    max_article_age_days: int = 30  # ignore feed/sitemap entries dated older than this (0 = no limit)

    # --- browser rendering ---
    playwright_enabled: bool = False
    playwright_timeout_ms: int = 20000

    # --- extraction ---
    min_article_words: int = 120
    article_score_threshold: float = 0.5
    llm_enabled: bool = False
    llm_confidence_threshold: float = 0.55
    llm_provider: str = "groq"  # groq | anthropic
    llm_model: str = "claude-opus-5"  # Anthropic model (when LLM_PROVIDER=anthropic)
    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-120b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    llm_max_input_chars: int = 60000
    anthropic_api_key: str | None = None

    # --- dedup ---
    simhash_max_distance: int = 3

    # --- storage ---
    store_raw_html_default: bool = False

    # --- search ---
    search_backend: str = "auto"  # auto | postgres | basic

    # --- metrics ---
    metrics_enabled: bool = True

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_key or self.supabase_url)

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


@lru_cache
def get_settings() -> Settings:
    return Settings()
