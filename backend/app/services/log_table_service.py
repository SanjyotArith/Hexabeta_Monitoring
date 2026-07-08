"""
LogTableService — manages per-service dynamic log tables.

Each service gets its own table:  logs_nginx, logs_backend, logs_backend_error, etc.
Tables are created on first use and cached in memory.
"""
import re
import asyncio
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

# In-memory cache: service_name -> table_name (populated at startup + on demand)
_KNOWN_TABLES: set[str] = set()
_TABLE_LOCK = asyncio.Lock()

LOG_TABLE_PREFIX = "logs_"

# Services that existed in the old single `logs` table that we know about
KNOWN_SERVICES = [
    "nginx", "backend", "backend_error", "nginx_error",
    "postgres", "redis", "cloudflared", "deployment", "system"
]


def service_to_table(service_name: str) -> str:
    """Convert any service name string to a safe postgres table name."""
    clean = service_name.lower().strip()
    # Replace anything not alphanumeric with underscore
    clean = re.sub(r'[^a-z0-9]', '_', clean)
    # Collapse multiple underscores
    clean = re.sub(r'_+', '_', clean).strip('_')
    return f"{LOG_TABLE_PREFIX}{clean}"


def table_to_service(table_name: str) -> str:
    """Reverse: strip the logs_ prefix to get service name."""
    if table_name.startswith(LOG_TABLE_PREFIX):
        return table_name[len(LOG_TABLE_PREFIX):]
    return table_name


_CREATE_TABLE_TEMPLATE = """
CREATE TABLE IF NOT EXISTS {table_name} (
    id          BIGSERIAL PRIMARY KEY,
    machine_id  INTEGER REFERENCES machines(id) ON DELETE SET NULL,
    machine_name VARCHAR(100),
    timestamp   TIMESTAMP WITH TIME ZONE NOT NULL,
    received_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    log_level   VARCHAR(20),
    log_type    VARCHAR(50),
    severity    VARCHAR(20) NOT NULL DEFAULT 'info',
    message     TEXT NOT NULL,
    source_file TEXT,
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
)
"""

_CREATE_INDEXES_TEMPLATE = """
CREATE INDEX IF NOT EXISTS idx_{table_name}_ts  ON {table_name}(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_{table_name}_mc  ON {table_name}(machine_name);
CREATE INDEX IF NOT EXISTS idx_{table_name}_lvl ON {table_name}(log_level)
"""


async def ensure_service_table(db: AsyncSession, service_name: str) -> str:
    """Return table name for a service, creating the table if it doesn't exist yet."""
    table_name = service_to_table(service_name)

    if table_name in _KNOWN_TABLES:
        return table_name

    async with _TABLE_LOCK:
        if table_name in _KNOWN_TABLES:
            return table_name

        create_sql  = _CREATE_TABLE_TEMPLATE.format(table_name=table_name)
        indexes_sql = _CREATE_INDEXES_TEMPLATE.format(table_name=table_name)

        await db.execute(text(create_sql))
        # Execute each index statement individually
        for idx_stmt in indexes_sql.strip().split(';'):
            idx_stmt = idx_stmt.strip()
            if idx_stmt:
                await db.execute(text(idx_stmt))

        await db.commit()
        _KNOWN_TABLES.add(table_name)
        print(f"[LOG_TABLES] Created: {table_name}")

    return table_name


async def load_existing_tables(db: AsyncSession) -> list[str]:
    """
    Load all logs_* tables from information_schema on startup.
    Populates the in-memory cache.
    """
    result = await db.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = current_schema() "
        "  AND table_name LIKE 'logs\\_%' ESCAPE '\\\\' "
        "ORDER BY table_name"
    ))
    tables = [row[0] for row in result.fetchall()]
    _KNOWN_TABLES.update(tables)
    return tables


async def get_all_log_tables(db: AsyncSession) -> list[str]:
    """Return all known log tables, refreshing from DB if needed."""
    if not _KNOWN_TABLES:
        await load_existing_tables(db)
    return sorted(_KNOWN_TABLES)


async def insert_log_rows(db: AsyncSession, table_name: str, rows: list[dict]) -> None:
    """Bulk-insert parsed log rows into the given service table."""
    if not rows:
        return
    for row in rows:
        await db.execute(text(f"""
            INSERT INTO {table_name}
                (machine_id, machine_name, timestamp, received_at, log_level, log_type, severity, message, source_file)
            VALUES
                (:machine_id, :machine_name, :timestamp, :received_at, :log_level, :log_type, :severity, :message, :source_file)
        """), row)
