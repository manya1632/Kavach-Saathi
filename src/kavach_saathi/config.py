from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_mode: Literal["demo", "live"] = "demo"
    app_name: str = "Kavach Saathi Agents"
    api_prefix: str = "/v1"
    frontend_origin: str = "http://localhost:3000"
    data_dir: Path = Path("data/seed")
    asset_dir: Path = Path("assets/mock")
    media_storage_backend: Literal["auto", "local", "s3"] = "auto"
    media_endpoint_url: str | None = None
    media_access_key_id: str | None = None
    media_secret_access_key: str | None = None
    media_public_base_url: str | None = None
    media_local_read_fallback: bool = True
    media_presign_expiry_seconds: int = Field(default=900, ge=60, le=86400)
    catalogue_postgres_search_enabled: bool = True
    catalogue_fuzzy_search_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    catalogue_search_candidate_limit: int = Field(default=1000, ge=50, le=10_000)

    database_url: str = "postgresql+psycopg://kavach:kavach@localhost:5432/kavach_saathi"
    database_read_url: str | None = None
    database_ssl_mode: Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] | None = None
    database_connect_timeout_seconds: int = Field(default=10, ge=1, le=120)
    database_statement_timeout_ms: int = Field(default=0, ge=0, le=600_000)
    database_application_name: str = "kavach-saathi"
    database_read_pool_size: int = Field(default=5, ge=1, le=100)
    require_read_database_ready: bool = False
    redis_url: str = "redis://localhost:6379/0"
    redis_cache_url: str | None = None
    redis_stream_url: str | None = None
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=20, ge=0, le=200)
    database_pool_timeout_seconds: int = Field(default=30, ge=1, le=120)
    database_pool_recycle_seconds: int = Field(default=1800, ge=60, le=86400)
    redis_max_connections: int = Field(default=50, ge=5, le=1000)
    redis_socket_timeout_seconds: float = Field(default=5.0, ge=3.0, le=30)
    redis_socket_connect_timeout_seconds: float = Field(default=5.0, ge=1.0, le=30)
    redis_retry_on_timeout: bool = True

    # Fixed-window limits protect only abuse-sensitive write endpoints. They fail
    # open when Redis is unavailable so a cache outage cannot take commerce down.
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = Field(default=60, ge=10, le=3600)
    run_event_consumers_in_web: bool = True
    run_workflows_in_web: bool = True
    deployment_environment: str = "local"
    release_version: str = "development"
    require_worker_ready: bool = False
    worker_heartbeat_ttl_seconds: int = Field(default=15, ge=6, le=120)

    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_token_minutes: int = Field(default=30, ge=5, le=1440)
    jwt_refresh_token_days: int = Field(default=14, ge=1, le=90)

    nano_banana_daily_quota: int = Field(default=15, ge=1, le=1000)
    gemini_api_key: str | None = None
    gemini_image_model: str = "gemini-3.1-flash-image"
    gemini_reasoning_model: str = "gemini-3.5-flash"
    huggingface_api_key: str | None = None
    huggingface_image_model: str = "black-forest-labs/FLUX.1-Kontext-dev"
    fashn_space_id: str = "fashn-ai/fashn-vton-1.5"
    fashn_api_key: str | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-6"
    pinecone_api_key: str | None = None
    pinecone_environment: str | None = None
    pinecone_size_index: str = "kavach-saathi-size-rag"
    pinecone_qa_index: str = "kavach-saathi-voice-qa"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    warm_up_on_startup: bool = False
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_webhook_secret: str | None = None
    digilocker_client_id: str | None = None
    digilocker_client_secret: str | None = None
    google_maps_api_key: str | None = None
    google_vision_api_key: str | None = None

    groq_api_key: str | None = None
    external_secret_arn: str | None = None
    groq_model: str = "openai/gpt-oss-120b"
    groq_vision_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    groq_reasoning_effort: Literal["low", "medium", "high"] = "medium"
    reasoning_mode: Literal["demo", "groq"] = "demo"

    aws_region: str = "ap-south-1"
    workflow_table: str = "kavach-saathi-workflows"
    domain_table: str = "kavach-saathi-domain"
    media_bucket: str = "kavach-saathi-media"
    nova_model_id: str = "amazon.nova-2-lite-v1:0"
    nova_canvas_model_id: str = "amazon.nova-canvas-v1:0"
    model_template_keys: str = ""
    state_machine_arn: str | None = None

    bhashini_user_id: str | None = None
    bhashini_api_key: str | None = None
    bhashini_pipeline_id: str | None = None
    bhashini_config_url: str = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"

    # Sarvam AI -- free-tier substitute for Bhashini's ASR/TTS (Agent 5 voice Q&A,
    # Agent 7 verification call), see project notes: Bhashini requires an institutional
    # SPOC to get API access, which blocks an individual hackathon build. One key covers
    # Speech-to-Text (Saaras) and Text-to-Speech (Bulbul).
    sarvam_api_key: str | None = None

    google_application_credentials: str | None = None
    google_service_account_json: str | None = None

    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from_number: str | None = None
    twilio_whatsapp_from: str = "whatsapp:+14155238886"  # Twilio's shared sandbox number
    otp_demo_code: str | None = None
    allow_demo_otp: bool = False
    otp_expiry_seconds: int = Field(default=300, ge=60, le=900)
    otp_resend_cooldown_seconds: int = Field(default=60, ge=15, le=300)
    otp_max_attempts: int = Field(default=3, ge=1, le=10)

    # Publicly reachable base URL for this backend (e.g. an ngrok tunnel) -- Twilio's
    # servers must be able to reach us to fetch call instructions and post back the
    # buyer's recorded response; localhost is not reachable from Twilio's cloud.
    public_base_url: str | None = None
    agent7_max_retries: int = Field(default=2, ge=0, le=5)

    twilio_verify_service_sid: str | None = None
    twilio_order_confirmation_content_sid: str | None = None
    twilio_delivery_date_content_sid: str | None = None
    twilio_reschedule_content_sid: str | None = None
    twilio_cancellation_content_sid: str | None = None
    max_agent_iterations: int = Field(default=4, ge=1, le=8)
    provider_timeout_seconds: float = Field(default=30.0, ge=1, le=120)

    @model_validator(mode="after")
    def validate_live_mode(self) -> Settings:
        if self.app_mode == "live" and not (self.groq_api_key or self.external_secret_arn):
            raise ValueError("GROQ_API_KEY or EXTERNAL_SECRET_ARN is required when APP_MODE=live")
        if self.reasoning_mode == "groq" and not self.groq_api_key:
            raise ValueError("GROQ_API_KEY is required when REASONING_MODE=groq")
        return self

    @property
    def is_live(self) -> bool:
        return self.app_mode == "live"

    @property
    def uses_groq(self) -> bool:
        return self.is_live or self.reasoning_mode == "groq"

    @property
    def uses_gemini_reasoning(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def uses_object_storage(self) -> bool:
        return self.media_storage_backend == "s3" or (
            self.media_storage_backend == "auto" and self.is_live
        )

    @property
    def model_templates(self) -> list[str]:
        return [value.strip() for value in self.model_template_keys.split(",") if value.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
