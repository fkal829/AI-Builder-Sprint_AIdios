from functools import lru_cache

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

    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "contracts"

    upstage_mode: str = "mock"
    upstage_api_key: str = ""
    upstage_base_url: str = "https://api.upstage.ai"

    modusign_mode: str = "mock"
    modusign_api_key: str = ""
    modusign_template_id: str = ""
    modusign_webhook_secret: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
