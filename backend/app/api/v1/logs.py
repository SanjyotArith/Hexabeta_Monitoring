"""
Logs API — per-service table architecture.

POST  /logs/push       — receive batches from HexaAgent, parse, persist, broadcast
WS    /logs/live       — WebSocket: streams newly stored logs to connected clients
GET   /logs/history    — paginated query across one or all service tables
GET   /logs/services   — list of services that have a log table
GET   /logs/machines   — distinct machine names across all log tables
GET   /logs/{service}  — legacy compat: returns latest 100 rows for a service
"""

import re
import json
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Depends, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import get_db
from app.models.infrastructure import Machine, Environment
from sqlalchemy.future import select
from app.services.log_table_service import (
    ensure_service_table,
    get_all_log_tables,
    insert_log_rows,
    table_to_service,
    service_to_table,
)

router = APIRouter()


# ─── WebSocket Connection Manager ────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket):
        self._connections.discard(ws) if hasattr(self._connections, 'discard') else None
        if ws in self._connections:
            self._connections.remove(ws)

    async def broadcast(self, payload: str):
        dead = []
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

manager = ConnectionManager()


# ─── Log Line Parser ──────────────────────────────────────────────────────────

def parse_log_line(line: str):
    """
    Extracts (timestamp, log_level, message) from a raw log line.
    Handles Nginx, ISO-8601, and plain-text formats.
    """
    timestamp = datetime.now(timezone.utc)
    log_level = "INFO"
    message   = line

    # Nginx combined log: [04/Jul/2026:14:52:31 +0530]
    nginx_m = re.search(r'\[(\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})\]', line)
    if nginx_m:
        try:
            timestamp = datetime.strptime(nginx_m.group(1), "%d/%b/%Y:%H:%M:%S %z").astimezone(timezone.utc)
        except Exception:
            pass
    else:
        # ISO-8601 / common log timestamp
        iso_m = re.search(r'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)', line)
        if iso_m:
            try:
                import dateutil.parser
                dt = dateutil.parser.isoparse(iso_m.group(1))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                timestamp = dt.astimezone(timezone.utc)
            except Exception:
                pass

    # Extract log level keyword
    level_m = re.search(r'\b(INFO|ERROR|WARNING|WARN|DEBUG|CRITICAL)\b', line, re.IGNORECASE)
    if level_m:
        log_level = level_m.group(1).upper()
        if log_level == "WARN":
            log_level = "WARNING"

    # Strip leading "LEVEL: " prefix from message
    clean_m = re.match(r'^(?:INFO|ERROR|WARNING|WARN|DEBUG|CRITICAL):\s*(.*)', line, re.IGNORECASE)
    if clean_m:
        message = clean_m.group(1)

    return timestamp, log_level, message


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/push")
async def push_logs(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Receive a log batch from HexaAgent:
    {
      "machine_name": "MacHexa",
      "service": "nginx",
      "lines": ["...", "..."]
    }
    Every line is parsed, written to the service-specific table, then broadcast.
    """
    try:
        data = await request.json()

        # Debug dump (unchanged behaviour)
        try:
            with open("logs_payload_debug.json", "a") as f:
                f.write(json.dumps(data) + "\n")
        except Exception:
            pass

        machine_name = data.get("machine_name", "Unknown")
        service_name = data.get("service", "system")
        lines        = data.get("lines", [])

        if not lines:
            return {"status": "success", "message": "No lines in batch"}

        # Ensure the service-specific table exists
        table_name = await ensure_service_table(db, service_name)

        # Resolve machine_id (create machine record if missing)
        machine_id = None
        machine_res = await db.execute(select(Machine).where(Machine.name == machine_name))
        machine = machine_res.scalars().first()
        if not machine:
            env_res = await db.execute(select(Environment).limit(1))
            env = env_res.scalars().first()
            if env:
                machine = Machine(environment_id=env.id, name=machine_name, os="unknown")
                db.add(machine)
                await db.flush()
                await db.refresh(machine)
        if machine:
            machine_id = machine.id

        # Parse and prepare rows
        now = datetime.now(timezone.utc)
        rows = []
        broadcast_items = []
        for line in lines:
            if not line:
                continue
            ts, level, msg = parse_log_line(line)
            row = {
                "machine_id":   machine_id,
                "machine_name": machine_name,
                "timestamp":    ts,
                "received_at":  now,
                "log_level":    level,
                "log_type":     service_name,
                "severity":     level.lower(),
                "message":      msg,
                "source_file":  None,
            }
            rows.append(row)
            broadcast_items.append({
                "machine_name": machine_name,
                "service_name": service_name,
                "timestamp":    ts.isoformat(),
                "log_level":    level,
                "message":      msg,
            })

        await insert_log_rows(db, table_name, rows)
        await db.commit()

        # Broadcast to all connected WebSocket clients
        if broadcast_items:
            asyncio.create_task(manager.broadcast(json.dumps(broadcast_items)))

        return {"status": "success", "message": f"Stored {len(rows)} logs → {table_name}"}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


@router.websocket("/live")
async def ws_live(websocket: WebSocket):
    """WebSocket endpoint — pushes newly stored log batches to the UI."""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()   # keep-alive ping from client
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


@router.get("/services")
async def list_services(db: AsyncSession = Depends(get_db)):
    """Returns list of services that have a dedicated log table."""
    tables = await get_all_log_tables(db)
    services = [table_to_service(t) for t in tables]
    return {"status": "success", "services": services}


@router.get("/machines")
async def list_machines(db: AsyncSession = Depends(get_db)):
    """Returns distinct machine names across all log tables."""
    tables = await get_all_log_tables(db)
    if not tables:
        return {"status": "success", "machines": []}

    parts = [f"SELECT DISTINCT machine_name FROM {t}" for t in tables]
    union_sql = " UNION ".join(parts) + " ORDER BY machine_name"
    result = await db.execute(text(union_sql))
    machines = [row[0] for row in result.fetchall() if row[0]]
    return {"status": "success", "machines": machines}


@router.get("/history")
async def history(
    machine_name: str = Query(None),
    service_name: str = Query(None),
    log_level:    str = Query(None),
    search:       str = Query(None),
    time_preset:  str = Query("1h"),
    start_time:   str = Query(None),
    end_time:     str = Query(None),
    page:         int = Query(1, ge=1),
    limit:        int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """
    Query log history across all (or a specific) service table(s).

    Filters: machine_name, service_name, log_level, search (text), time range.
    Sorting:  newest first.
    Pagination: page / limit.
    """
    import datetime as dt

    # ── Resolve time range ───────────────────────────────────────────────
    now = datetime.now(timezone.utc)

    presets = {
        "30s": dt.timedelta(seconds=30),
        "1m":  dt.timedelta(minutes=1),
        "5m":  dt.timedelta(minutes=5),
        "10m": dt.timedelta(minutes=10),
        "30m": dt.timedelta(minutes=30),
        "1h":  dt.timedelta(hours=1),
        "3h":  dt.timedelta(hours=3),
        "6h":  dt.timedelta(hours=6),
        "12h": dt.timedelta(hours=12),
        "24h": dt.timedelta(hours=24),
    }

    ts_from = None
    ts_to   = None

    if time_preset and time_preset != "Custom" and time_preset in presets:
        ts_from = now - presets[time_preset]
    elif start_time or end_time:
        import dateutil.parser
        if start_time:
            ts_from = dateutil.parser.isoparse(start_time)
        if end_time:
            ts_to = dateutil.parser.isoparse(end_time)

    # ── Determine which tables to query ─────────────────────────────────
    if service_name and service_name != "All":
        target_table = service_to_table(service_name)
        all_tables = await get_all_log_tables(db)
        tables = [target_table] if target_table in all_tables else []
    else:
        tables = await get_all_log_tables(db)

    if not tables:
        return {"status": "success", "total": 0, "page": page, "limit": limit, "logs": []}

    # ── Build WHERE clauses ──────────────────────────────────────────────
    params: dict = {}
    where_parts = []

    if machine_name and machine_name != "All":
        where_parts.append("machine_name = :machine_name")
        params["machine_name"] = machine_name
    if log_level and log_level != "All":
        where_parts.append("log_level = :log_level")
        params["log_level"] = log_level
    if search:
        where_parts.append("message ILIKE :search")
        params["search"] = f"%{search}%"
    if ts_from:
        where_parts.append("timestamp >= :ts_from")
        params["ts_from"] = ts_from
    if ts_to:
        where_parts.append("timestamp <= :ts_to")
        params["ts_to"] = ts_to

    where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    # ── Build UNION ALL across tables ────────────────────────────────────
    sub_selects = []
    for tbl in tables:
        svc = table_to_service(tbl)
        sub_selects.append(
            f"SELECT id::text, machine_name, '{svc}' AS service_name, "
            f"timestamp, log_level, message "
            f"FROM {tbl} {where_sql}"
        )

    union_sql = " UNION ALL ".join(sub_selects)

    # ── Count ────────────────────────────────────────────────────────────
    count_sql = f"SELECT COUNT(*) FROM ({union_sql}) AS combined"
    count_res = await db.execute(text(count_sql), params)
    total = count_res.scalar() or 0

    # ── Paginated fetch ──────────────────────────────────────────────────
    offset = (page - 1) * limit
    data_sql = (
        f"SELECT id, machine_name, service_name, timestamp, log_level, message "
        f"FROM ({union_sql}) AS combined "
        f"ORDER BY timestamp DESC "
        f"LIMIT :limit OFFSET :offset"
    )
    params["limit"]  = limit
    params["offset"] = offset

    rows_res = await db.execute(text(data_sql), params)
    rows = rows_res.fetchall()

    return {
        "status": "success",
        "total":  total,
        "page":   page,
        "limit":  limit,
        "logs": [
            {
                "id":           str(r[0]),
                "machine_name": r[1],
                "service_name": r[2],
                "timestamp":    r[3].isoformat() if r[3] else None,
                "log_level":    r[4],
                "message":      r[5],
            }
            for r in rows
        ],
    }


@router.get("/{service}")
async def get_service_logs_legacy(service: str, db: AsyncSession = Depends(get_db)):
    """
    Legacy compatibility: returns the latest 100 logs for `service`.
    Used by Dashboard LogsSection (old polling).
    """
    table_name = service_to_table(service)
    all_tables = await get_all_log_tables(db)

    if table_name not in all_tables:
        return {"logs": [], "lines": []}

    result = await db.execute(text(
        f"SELECT log_level, message, timestamp FROM {table_name} "
        f"ORDER BY timestamp DESC LIMIT 100"
    ))
    rows = result.fetchall()

    logs  = [{"severity": r[0], "message": r[1], "timestamp": r[2].strftime("%H:%M:%S")} for r in rows]
    lines = [f"{r[0]}: {r[1]}" for r in reversed(rows)]
    return {"logs": logs, "lines": lines}
