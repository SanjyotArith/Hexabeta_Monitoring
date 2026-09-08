"""
HexaMonitor & HexaAgent — Unified Application Configuration.

Loads environment variables from workspace .env files while maintaining full backward
compatibility for both HexaMonitor server and HexaAgent daemon settings.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional, List

from pydantic_settings import BaseSettings, SettingsConfigDict


def load_env_file():
    """Locates and loads the workspace .env file by checking current and parent folders."""
    paths_to_check = [".env", "../.env", "../../.env"]
    for path in paths_to_check:
        if os.path.exists(path):
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip("'\"")
                        if key not in os.environ:
                            os.environ[key] = val
            break


# Load environment configuration into os.environ if not already present
load_env_file()


class Settings(BaseSettings):
    """Unified application settings for HexaMonitor & HexaAgent."""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------------------------------------------------------------------------
    # HexaMonitor Server Settings
    # ---------------------------------------------------------------------------
    PROJECT_NAME: str = "HexaMonitor"
    API_V1_STR: str = "/api/v1"

    # Security Configurations
    SECRET_KEY: str = "9e81b67484dfd0f81d86d63e7cf0c79e6bc7c3e59ea16027a052ff37c862901e"
    AGENT_KEY: str = "default-agent-key"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Database Settings
    PGHOST: str = "localhost"
    PGPORT: int = 5432
    PGUSER: str = "postgres"
    PGPASSWORD: str = ""
    PGDATABASE: str = "hexa_monitor"
    PGSCHEMA: str = "hexa"

    @property
    def DATABASE_URL(self) -> str:
        """Returns synchronous database connection URL (for Alembic migrations)."""
        import urllib.parse
        encoded_password = urllib.parse.quote_plus(self.PGPASSWORD)
        return f"postgresql://{self.PGUSER}:{encoded_password}@{self.PGHOST}:{self.PGPORT}/{self.PGDATABASE}"

    @property
    def ASYNC_DATABASE_URL(self) -> str:
        """Returns asynchronous database connection URL (for application sessions)."""
        import urllib.parse
        encoded_password = urllib.parse.quote_plus(self.PGPASSWORD)
        return f"postgresql+asyncpg://{self.PGUSER}:{encoded_password}@{self.PGHOST}:{self.PGPORT}/{self.PGDATABASE}"

    # ---------------------------------------------------------------------------
    # HexaAgent Telemetry & Provider Settings
    # ---------------------------------------------------------------------------
    # HexaBeta Project Paths
    HEXABETA_PROJECT_ROOT: str = "/opt/hexabeta/arithwise-HBv1"
    HEXABETA_BACKEND_PATH: str = "/opt/hexabeta/arithwise-HBv1/backend"
    HEXABETA_FRONTEND_PATH: str = "/opt/hexabeta/arithwise-HBv1/frontend"
    HEXABETA_UPLOADS_PATH: str = "/opt/hexabeta/arithwise-HBv1/uploads"

    HEXABETA_BACKEND_PORT: int = 8002

    REFRESH_INTERVAL: int = 5
    HOST: str = "0.0.0.0"
    PORT: int = 9000

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

    # Reporter Settings
    MONITOR_URL: str = "https://hexamonitor.spicykheer.com"
    API_PREFIX: str = "/api/v1"
    REPORT_ENDPOINT: str = "/agents/report"
    SNAPSHOT_PUSH_ENDPOINT: str = "/snapshot/push"
    LOGS_PUSH_ENDPOINT: str = "/logs/push"
    LOGS_PUSH_INTERVAL: int = 5
    OPERATIONS_POLL_ENDPOINT: str = "/operations/pending"
    OPERATIONS_POLL_INTERVAL: int = 5
    MACHINE_NAME: str = "MacHexa-Prod-01"
    ENVIRONMENT: str = "production"
    COLLECTION_INTERVAL: int = 60
    REQUEST_TIMEOUT: float = 10.0
    VERIFY_SSL: bool = True
    LOG_LEVEL: str = "INFO"
    DEBUG: bool = False

    # Feature Flags
    ENABLE_OPERATIONS_POLLER: bool = False
    ENABLE_LOG_PUSHER: bool = False

    def _build_url(self, endpoint: str) -> str:
        """
        Safely construct a full URL combining MONITOR_URL, API_PREFIX, and endpoint,
        ensuring that API_PREFIX is added exactly once without duplication.
        """
        base = self.MONITOR_URL.rstrip("/")
        prefix = self.API_PREFIX.strip("/")
        ep = endpoint.strip("/")

        if prefix:
            if base.endswith(f"/{prefix}"):
                base = base[:-len(f"/{prefix}")]
            elif base.endswith(prefix):
                base = base[:-len(prefix)].rstrip("/")

            if ep == prefix:
                ep = ""
            elif ep.startswith(f"{prefix}/"):
                ep = ep[len(f"{prefix}/"):]

        parts = [p for p in [base, prefix, ep] if p]
        return "/".join(parts)

    @property
    def full_report_url(self) -> str:
        return self._build_url(self.REPORT_ENDPOINT)

    @property
    def full_snapshot_push_url(self) -> str:
        return self._build_url(self.SNAPSHOT_PUSH_ENDPOINT)

    @property
    def full_logs_push_url(self) -> str:
        return self._build_url(self.LOGS_PUSH_ENDPOINT)

    @property
    def full_operations_poll_url(self) -> str:
        return self._build_url(self.OPERATIONS_POLL_ENDPOINT)

    # Phase 2A: Backend Provider
    BACKEND_INTERNAL_HEALTH_URL: str = "http://localhost:8002/api/health"
    BACKEND_EXTERNAL_HEALTH_URL: str = "https://hexabeta.com/api/health"
    BACKEND_LAUNCH_LABEL: str = "com.hexa.backend"

    # Docker Awareness
    DOCKER_ENABLED: bool = True
    BACKEND_MODE: str = "auto"
    HEXABETA_BACKEND_CONTAINER_PATTERNS: str = "hexabeta_backend,hexabeta_backend_green"
    DOCKER_COMMAND_TIMEOUT: int = 5

    @property
    def backend_container_patterns(self) -> list[str]:
        raw = self.HEXABETA_BACKEND_CONTAINER_PATTERNS.strip()
        if not raw:
            return []
        return [p.strip() for p in raw.split(",") if p.strip()]

    # Phase 2A: PostgreSQL Provider
    POSTGRES_SERVICE: str = "postgresql@17"
    POSTGRES_MODE: str = "auto"
    POSTGRES_HOST: str = "127.0.0.1"
    POSTGRES_PORT: int = 5432
    POSTGRES_DATABASE: str = "loops_db"
    POSTGRES_USER: str = "hexa_user"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_CONTAINER_PATTERNS: str = "hexabeta_postgres,hexabeta_postgres_main"

    @property
    def postgres_container_patterns(self) -> list[str]:
        raw = self.POSTGRES_CONTAINER_PATTERNS.strip()
        if not raw:
            return []
        return [p.strip() for p in raw.split(",") if p.strip()]

    # Phase 2A: Redis Provider
    REDIS_SERVICE: str = "redis"
    REDIS_MODE: str = "auto"
    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    REDIS_CONTAINER_PATTERNS: str = "hexabeta_redis"

    @property
    def redis_container_patterns(self) -> list[str]:
        raw = self.REDIS_CONTAINER_PATTERNS.strip()
        if not raw:
            return []
        return [p.strip() for p in raw.split(",") if p.strip()]

    # Phase 2A: Nginx Provider
    NGINX_LABEL: str = "com.hexabeta.nginx"
    NGINX_HTTP: str = "http://127.0.0.1"
    NGINX_HTTPS: str = "https://127.0.0.1"

    # Phase 2A: Cloudflared Provider
    CLOUDFLARED_TUNNEL: str = "mac-mini"

    # Phase 2A: Git Provider
    GIT_PROJECT_PATH: str = ""

    # Phase 2A: Deploy
    DEPLOY_SCRIPT: str = ""

    # Phase 2A: Snapshot Engine
    SNAPSHOT_INTERVAL: int = 5

    @property
    def git_project_path_resolved(self) -> Path:
        return Path(self.GIT_PROJECT_PATH) if self.GIT_PROJECT_PATH else self.project_root

    # Phase 2B: Security Settings
    OPERATION_TOKEN: str = "HB_ops_super_secret_token_12345!"

    # Phase 2B: Log File Paths
    BACKEND_LOG_PATH: str = "/Users/hexabeta/backend.log"
    BACKEND_ERROR_LOG_PATH: str = "/Users/hexabeta/backend-error.log"
    NGINX_LOG_PATH: str = "/opt/homebrew/var/log/nginx/access.log"
    NGINX_ERROR_LOG_PATH: str = "/opt/homebrew/var/log/nginx/error.log"
    REDIS_LOG_PATH: str = "/opt/homebrew/var/log/redis.log"
    POSTGRES_LOG_PATH: str = "/opt/homebrew/var/postgresql@17/log/"
    CLOUDFLARED_LOG_PATH: str = "/Users/hexabeta/.cloudflared/cloudflared.log"
    DEPLOYMENT_LOG_PATH: str = "/Users/hexabeta/hb-deploy.log"

    # Phase 2B: Alert Thresholds
    ALERT_CPU_THRESHOLD: float = 80.0
    ALERT_MEMORY_THRESHOLD: float = 90.0
    ALERT_DISK_THRESHOLD: float = 85.0
    ALERT_GPU_THRESHOLD: float = 85.0

    # Phase 2B: History Engine
    HISTORY_SAVE_INTERVAL: int = 300


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton of the application settings."""
    return Settings()


# Primary settings instance for HexaMonitor server & legacy imports
settings = get_settings()
