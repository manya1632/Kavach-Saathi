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

    database_url: str = "postgresql+psycopg://kavach:kavach@localhost:5432/kavach_saathi"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_token_minutes: int = Field(default=30, ge=5, le=1440)
    jwt_refresh_token_days: int = Field(default=14, ge=1, le=90)

    nano_banana_daily_quota: int = Field(default=15, ge=1, le=1000)
    gemini_api_key: str | None = None
    gemini_image_model: str = "gemini-3.1-flash-image"
    gemini_reasoning_model: str = "gemini-3.5-flash"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-6"
    pinecone_api_key: str | None = None
    pinecone_environment: str | None = None
    pinecone_size_index: str = "kavach-saathi-size-rag"
    pinecone_qa_index: str = "kavach-saathi-voice-qa"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
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

    # Publicly reachable base URL for this backend (e.g. an ngrok tunnel) -- Twilio's
    # servers must be able to reach us to fetch call instructions and post back the
    # buyer's recorded response; localhost is not reachable from Twilio's cloud.
    public_base_url: str | None = None
    agent7_max_retries: int = Field(default=2, ge=0, le=5)

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
    def model_templates(self) -> list[str]:
        return [value.strip() for value in self.model_template_keys.split(",") if value.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
