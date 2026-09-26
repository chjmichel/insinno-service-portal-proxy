from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Mandatory iCore connection settings.
    icore_base_url: str = "https://c03-insinno-internal-dev.insinno.de/"
    icore_api_path: str = "/api/v2/icore"
    icore_login_origin: str = "https://c03-insinno-internal-dev.insinno.de/"
    icore_timeout_seconds: float = 10.0
    icore_verify_ssl: bool = False

    require_authentication: bool = True
    token_cache_seconds: int = 300

    semantics_config_path: str = "config/semantics.json"
    use_mock_data: bool = False
    mock_data_path: str = "config/mock/icore-api.json"

    cors_origins: str = "http://localhost:5173"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    @property
    def icore_api_url(self) -> str:
        return f"{self.icore_base_url.rstrip('/')}/{self.icore_api_path.strip('/')}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
