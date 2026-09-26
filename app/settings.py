from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    icore_base_url: str
    icore_api_path: str = "/api/v2/icore"
    icore_login_origin: str
    icore_userinfo_path: str = "/loggedUser"
    icore_timeout_seconds: float = 30.0
    icore_verify_ssl: bool = True

    require_authentication: bool = True
    token_cache_seconds: int = 300

    auth_cookie_name: str = "service_portal_icore"
    auth_cookie_secure: bool = True
    auth_cookie_samesite: str = "lax"
    auth_cookie_max_age: int = 3600

    semantics_config_path: str = "config/semantics.json"
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
