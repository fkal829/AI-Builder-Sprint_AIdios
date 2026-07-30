from functools import lru_cache
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"
    app_name: str = "안심홍보계약 API"
    api_v1_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:3000"
    public_app_base_url: str = "http://localhost:3000"

    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "contracts"
    supabase_mode: Literal["mock", "live"] = "mock"
    supabase_mock_storage_access_base_url: str = (
        "http://localhost:8000/api/v1/_mock/storage"
    )

    document_max_size_mib: int = Field(default=20, ge=1, le=100)
    document_max_pdf_pages: int = Field(default=100, ge=1, le=500)
    demo_owner_id: UUID = UUID("00000000-0000-4000-8000-000000000013")
    demo_contract_id: UUID = UUID("00000000-0000-4000-8000-000000000041")
    demo_bearer_token: str = Field(default="local-demo-owner-token", min_length=16)
    public_token_secret: str = Field(
        default="local-development-public-token-secret-change-before-production",
        min_length=32,
    )

    upstage_mode: Literal["mock", "live"] = "mock"
    upstage_api_key: str = ""
    upstage_base_url: str = "https://api.upstage.ai"
    upstage_parse_timeout_seconds: float = Field(default=120, ge=1, le=300)
    upstage_extract_timeout_seconds: float = Field(default=180, ge=1, le=600)
    upstage_extract_model: str = "information-extract"

    modusign_mode: str = "mock"
    modusign_api_key: str = ""
    modusign_template_id: str = ""
    modusign_webhook_secret: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def document_max_size_bytes(self) -> int:
        return self.document_max_size_mib * 1024 * 1024

    @model_validator(mode="after")
    def validate_external_modes(self) -> "Settings":
        if self.supabase_mode == "live" and (
            not self.supabase_url or not self.supabase_service_role_key
        ):
            raise ValueError(
                "SUPABASE_MODE=live에는 SUPABASE_URL과 SUPABASE_SERVICE_ROLE_KEY가 필요합니다."
            )
        if self.upstage_mode == "live" and not self.upstage_api_key:
            raise ValueError("UPSTAGE_MODE=live에는 UPSTAGE_API_KEY가 필요합니다.")
        if self.app_env == "production" and self.supabase_mode == "mock":
            raise ValueError("production에서는 SUPABASE_MODE=mock을 사용할 수 없습니다.")
        if (
            self.app_env == "production"
            and self.public_token_secret
            == "local-development-public-token-secret-change-before-production"
        ):
            raise ValueError("production에서는 PUBLIC_TOKEN_SECRET을 별도로 설정해야 합니다.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
