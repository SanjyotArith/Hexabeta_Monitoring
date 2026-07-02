import os

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
                        os.environ[key] = val
            break

# Load environment configuration
load_env_file()

class Settings:
    PROJECT_NAME: str = "HexaMonitor"
    API_V1_STR: str = "/api/v1"
    
    # Security Configurations
    # In production, this must be a cryptographically secure 32+ byte string
    SECRET_KEY: str = os.environ.get("HEXAMONITOR_SECRET_KEY", "9e81b67484dfd0f81d86d63e7cf0c79e6bc7c3e59ea16027a052ff37c862901e")
    AGENT_KEY: str = os.environ.get("AGENT_KEY", "default-agent-key")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # Database Settings
    PGHOST: str = os.environ.get("PGHOST", "localhost")
    PGPORT: str = os.environ.get("PGPORT", "5432")
    PGUSER: str = os.environ.get("PGUSER", "postgres")
    PGPASSWORD: str = os.environ.get("PGPASSWORD", "")
    PGDATABASE: str = os.environ.get("PGDATABASE", "hexa_monitor")
    PGSCHEMA: str = os.environ.get("PGSCHEMA", "hexa")
    
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

settings = Settings()
