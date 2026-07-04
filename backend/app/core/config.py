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
    SNAPSHOT_PUSH_ENDPOINT: str = "/snapshot/push"
    LOGS_PUSH_ENDPOINT: str = "/logs/push"
    LOGS_PUSH_INTERVAL: int = 5
    OPERATIONS_POLL_ENDPOINT: str = "/operations/pending"
    OPERATIONS_POLL_INTERVAL: int = 5
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

    @property
    def full_snapshot_push_url(self) -> str:
        """Construct the full URL for the HexaMonitor snapshot push endpoint."""
        base = self.MONITOR_URL.rstrip("/")
        prefix = self.API_PREFIX.strip("/")
        endpoint = self.SNAPSHOT_PUSH_ENDPOINT.lstrip("/")
        return f"{base}/{prefix}/{endpoint}"

    @property
    def full_logs_push_url(self) -> str:
        """Construct the full URL for the HexaMonitor logs push endpoint."""
        base = self.MONITOR_URL.rstrip("/")
        prefix = self.API_PREFIX.strip("/")
        endpoint = self.LOGS_PUSH_ENDPOINT.lstrip("/")
        return f"{base}/{prefix}/{endpoint}"

    @property
    def full_operations_poll_url(self) -> str:
        """Construct the full URL for the HexaMonitor operations poll endpoint."""
        base = self.MONITOR_URL.rstrip("/")
        prefix = self.API_PREFIX.strip("/")
        endpoint = self.OPERATIONS_POLL_ENDPOINT.lstrip("/")
        return f"{base}/{prefix}/{endpoint}"

    # --- Phase 2A: Backend Provider ---
    BACKEND_INTERNAL_HEALTH_URL: str = "http://localhost:8002/api/health"
    BACKEND_EXTERNAL_HEALTH_URL: str = "https://hexabeta.com/api/health"
    BACKEND_LAUNCH_LABEL: str = "com.hexa.backend"

    # --- Phase 2A: PostgreSQL Provider ---
    POSTGRES_SERVICE: str = "postgresql@17"
    POSTGRES_PORT: int = 5432
    POSTGRES_DATABASE: str = "loops_db"
    POSTGRES_USER: str = "hexa_user"
    POSTGRES_PASSWORD: str = ""

    # --- Phase 2A: Redis Provider ---
    REDIS_SERVICE: str = "redis"
    REDIS_PORT: int = 6379

    # --- Phase 2A: Nginx Provider ---
    NGINX_LABEL: str = "com.hexabeta.nginx"
    NGINX_HTTP: str = "http://127.0.0.1"
    NGINX_HTTPS: str = "https://127.0.0.1"

    # --- Phase 2A: Cloudflared Provider ---
    CLOUDFLARED_TUNNEL: str = "mac-mini"

    # --- Phase 2A: Git Provider ---
    GIT_PROJECT_PATH: str = ""

    # --- Phase 2A: Deploy (read-only reference) ---
    DEPLOY_SCRIPT: str = ""

    # --- Phase 2A: Snapshot Engine ---
    SNAPSHOT_INTERVAL: int = 5

    @property
    def git_project_path_resolved(self) -> Path:
        return Path(self.GIT_PROJECT_PATH) if self.GIT_PROJECT_PATH else self.project_root

    # --- Phase 2B: Security Settings ---
    OPERATION_TOKEN: str = "HB_ops_super_secret_token_12345!"

    # --- Phase 2B: Log File Paths ---
    BACKEND_LOG_PATH: str = "/Users/hexabeta/backend.log"
    BACKEND_ERROR_LOG_PATH: str = "/Users/hexabeta/backend-error.log"
    NGINX_LOG_PATH: str = "/opt/homebrew/var/log/nginx/access.log"
    NGINX_ERROR_LOG_PATH: str = "/opt/homebrew/var/log/nginx/error.log"
    REDIS_LOG_PATH: str = "/opt/homebrew/var/log/redis.log"
    POSTGRES_LOG_PATH: str = "/opt/homebrew/var/postgresql@17/log/"
    CLOUDFLARED_LOG_PATH: str = "/Users/hexabeta/.cloudflared/cloudflared.log"
    DEPLOYMENT_LOG_PATH: str = "/Users/hexabeta/hb-deploy.log"

    # --- Phase 2B: Alert Thresholds ---
    ALERT_CPU_THRESHOLD: float = 80.0
    ALERT_MEMORY_THRESHOLD: float = 90.0
    ALERT_DISK_THRESHOLD: float = 85.0
    ALERT_GPU_THRESHOLD: float = 85.0

    # --- Phase 2B: History Engine ---
    HISTORY_SAVE_INTERVAL: int = 300



@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton of the application settings."""
    return Settings()
