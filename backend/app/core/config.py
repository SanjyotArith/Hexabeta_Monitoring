"""
HexaAgent — Application Configuration.

All settings are loaded from environment variables (.env file).
Nothing is hardcoded.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration loaded from .env file."""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- HexaBeta Project Paths ---
    HEXABETA_PROJECT_ROOT: str
    HEXABETA_BACKEND_PATH: str
    HEXABETA_FRONTEND_PATH: str
    HEXABETA_UPLOADS_PATH: str

    # --- HexaBeta Backend ---
    HEXABETA_BACKEND_PORT: int = 8002

    # --- Agent Settings ---
    REFRESH_INTERVAL: int = 5
    HOST: str = "0.0.0.0"
    PORT: int = 9000

    # Convenience — resolved Path objects
    @property
    def project_root(self) -> Path:
        return Path(self.HEXABETA_PROJECT_ROOT)

    @property
    def backend_path(self) -> Path:
        return Path(self.HEXABETA_BACKEND_PATH)

    @property
    def frontend_path(self) -> Path:
        return Path(self.HEXABETA_FRONTEND_PATH)

    @property
    def uploads_path(self) -> Path:
        return Path(self.HEXABETA_UPLOADS_PATH)

    # --- Reporter Settings ---
    MONITOR_URL: str = "https://hexamonitor.spicykheer.com"
    API_PREFIX: str = "/api/v1"
    REPORT_ENDPOINT: str = "/agents/report"
    AGENT_KEY: str = ""
    MACHINE_NAME: str = "MacHexa-Prod-01"
    PROJECT_NAME: str = "HexaBeta"
    ENVIRONMENT: str = "production"
    COLLECTION_INTERVAL: int = 60
    REQUEST_TIMEOUT: float = 10.0
    VERIFY_SSL: bool = True
    LOG_LEVEL: str = "INFO"
    DEBUG: bool = False

    @property
    def full_report_url(self) -> str:
        """Construct the full URL for the HexaMonitor report endpoint."""
        base = self.MONITOR_URL.rstrip("/")
        prefix = self.API_PREFIX.strip("/")
        endpoint = self.REPORT_ENDPOINT.lstrip("/")
        return f"{base}/{prefix}/{endpoint}"


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton of the application settings."""
    return Settings()
