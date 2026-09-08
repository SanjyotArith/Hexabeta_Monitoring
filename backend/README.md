# HexaAgent

**Lightweight production telemetry agent for the HexaBeta project.**

HexaAgent runs alongside the HexaBeta production server and continuously exposes live system metrics through REST APIs. It is designed to be consumed by **HexaMonitor** — a separate platform that stores historical data, generates dashboards, and triggers alerts.

> **HexaAgent is NOT part of HexaBeta.** It is a standalone monitoring agent.

---

## Quick Start

### 1. Prerequisites

- Python 3.10+
- pip

### 2. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your actual HexaBeta project paths
```

### 4. Run

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 9000
```

The agent will start on `http://0.0.0.0:9000`.

---

## API Endpoint

### `GET /api/v1/system`

Returns live telemetry for the HexaBeta project.

**Example Response:**

```json
{
  "success": true,
  "timestamp": "2026-07-02T10:00:00.000000+00:00",
  "cpu": {
    "cpu_percent": 18.24
  },
  "memory": {
    "memory_bytes": 314572800,
    "memory_mb": 300.0,
    "memory_gb": 0.2930
  },
  "storage": {
    "project_bytes": 1717986918,
    "project_mb": 1638.40,
    "project_gb": 1.6000,
    "backend_bytes": 524288000,
    "backend_mb": 500.0,
    "backend_gb": 0.4883,
    "frontend_bytes": 1073741824,
    "frontend_mb": 1024.0,
    "frontend_gb": 1.0000,
    "uploads_bytes": 119537094,
    "uploads_mb": 114.0,
    "uploads_gb": 0.1113
  },
  "gpu": {
    "model": "Apple M2 Pro",
    "vendor": "Apple",
    "core_count": 19,
    "metal_supported": true,
    "utilization": null
  }
}
```

> All values are **raw numerics**. Formatting belongs to the dashboard (HexaMonitor).

**Interactive docs:** `http://localhost:9000/docs`

---

## Project Architecture

```
backend/
├── app/
│   ├── api/
│   │   └── v1/
│   │       └── system.py          # GET /api/v1/system
│   ├── collectors/
│   │   ├── cpu.py                 # CPU usage collector
│   │   ├── memory.py              # RAM usage collector
│   │   ├── storage.py             # Disk footprint collector
│   │   └── gpu.py                 # GPU info collector
│   ├── core/
│   │   ├── config.py              # Pydantic settings from .env
│   │   └── registry.py            # Collector registry (plug-and-play)
│   ├── schemas/
│   │   └── system.py              # Pydantic response models
│   ├── utils/
│   │   └── process_finder.py      # HexaBeta process discovery
│   └── main.py                    # FastAPI app entry point
├── .env.example
├── requirements.txt
└── README.md
```

### Key Design Principles

| Principle | Implementation |
|---|---|
| **Modular** | Each collector is a standalone class inheriting `BaseCollector` |
| **Plug-and-play** | New collectors register via `collector_registry.register()` — zero changes to existing code |
| **HexaBeta-scoped** | Only monitors HexaBeta processes and directories — never the whole OS |
| **Raw values** | All metrics are raw numerics (bytes, percent) — no formatted strings |
| **Config-driven** | All paths and settings come from `.env` — nothing hardcoded |

---

## Collectors

### CPU Collector

- Discovers HexaBeta uvicorn processes by **backend path**, **backend port**, and **command-line**
- Finds the main process + all worker children
- Aggregates `cpu_percent` across all matched PIDs

### Memory Collector

- Uses the same process discovery as CPU
- Aggregates RSS (`memory_info().rss`) across all processes
- Returns bytes, MB, and GB

### Storage Collector

- Walks the configured project directories using `pathlib`
- Calculates total size for: project root, backend, frontend, uploads
- Never calculates whole-disk usage

### GPU Collector

- Runs `system_profiler SPDisplaysDataType -json` on macOS
- Reports: model, vendor, core count, Metal support
- **Utilization is always `null`** — macOS does not expose reliable per-process GPU metrics without kernel extensions
- Graceful fallback on non-macOS systems

---

## Configuration

All settings are loaded from the `.env` file. See [.env.example](.env.example) for the full list.

| Variable | Description | Default |
|---|---|---|
| `HEXABETA_PROJECT_ROOT` | Root path of the HexaBeta project | *required* |
| `HEXABETA_BACKEND_PATH` | Path to the HexaBeta backend | *required* |
| `HEXABETA_FRONTEND_PATH` | Path to the HexaBeta frontend | *required* |
| `HEXABETA_UPLOADS_PATH` | Path to the HexaBeta uploads directory | *required* |
| `HEXABETA_BACKEND_PORT` | Port the HexaBeta backend listens on | `8002` |
| `REFRESH_INTERVAL` | Suggested polling interval (seconds) | `5` |
| `HOST` | Host to bind HexaAgent to | `0.0.0.0` |
| `PORT` | Port to bind HexaAgent to | `9000` |
| `DOCKER_ENABLED` | Enable/disable Docker CLI awareness | `true` |
| `BACKEND_MODE` | Backend detection mode (`auto`, `host`, `docker`) | `auto` |
| `POSTGRES_MODE` | PostgreSQL detection mode (`auto`, `host`, `docker`) | `auto` |
| `REDIS_MODE` | Redis detection mode (`auto`, `host`, `docker`) | `auto` |
| `HEXABETA_BACKEND_CONTAINER_PATTERNS` | Comma-separated container name patterns | `hexabeta_backend,hexabeta_backend_green` |
| `POSTGRES_HOST` | PostgreSQL host address | `localhost` |
| `REDIS_HOST` | Redis host address | `localhost` |
| `ENABLE_OPERATIONS_POLLER` | Enable operations background poller | `false` |
| `ENABLE_LOG_PUSHER` | Enable background log pusher | `false` |

---

## Docker-Aware Deployment (GCP / Production)

HexaAgent can monitor services running in Docker containers (e.g. on GCP Linux VMs) as well as macOS host processes.

### Detection Modes
- **`auto` (default)**: Tries host process detection first. If no host process is found and Docker is enabled, automatically falls back to Docker container detection.
- **`docker`**: Skips host process detection and directly inspects Docker containers.
- **`host`**: Uses native host process / service detection only.

### Docker Requirements & Permissions
When running HexaAgent in Docker-aware mode:
1. The `docker` CLI must be installed on the host.
2. The user running HexaAgent must be added to the `docker` group (e.g., `sudo usermod -aG docker $USER`).
3. HexaAgent execution is **strictly read-only** (uses `docker ps`, `docker inspect`, `docker stats`, `docker info`). It never issues modification commands such as `stop`, `restart`, or `exec`.

### Example GCP Linux VM `.env`
```env
HEXABETA_PROJECT_ROOT=/opt/hexabeta
HEXABETA_BACKEND_PATH=/opt/hexabeta/backend
HEXABETA_FRONTEND_PATH=/opt/hexabeta/frontend
HEXABETA_UPLOADS_PATH=/opt/hexabeta/uploads

BACKEND_MODE=docker
POSTGRES_MODE=docker
REDIS_MODE=docker
DOCKER_ENABLED=true

HEXABETA_BACKEND_CONTAINER_PATTERNS=hexabeta_backend,hexabeta_backend_green
POSTGRES_CONTAINER_PATTERNS=postgres,hexabeta_postgres
REDIS_CONTAINER_PATTERNS=redis,hexabeta_redis

POSTGRES_HOST=localhost
REDIS_HOST=localhost

ENABLE_OPERATIONS_POLLER=false
ENABLE_LOG_PUSHER=false
```

---

## License

Internal project — not for public distribution.

