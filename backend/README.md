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

---

## Future Roadmap

The architecture is designed to support the following collectors **without changing existing code** — just add a new collector class and register it.

| Phase | Collector | Status |
|---|---|---|
| 1 | CPU | ✅ Implemented |
| 1 | Memory | ✅ Implemented |
| 1 | Storage | ✅ Implemented |
| 1 | GPU | ✅ Implemented |
| 2 | PostgreSQL | 🔲 Planned |
| 2 | MongoDB | 🔲 Planned |
| 2 | Redis | 🔲 Planned |
| 3 | Nginx | 🔲 Planned |
| 3 | Cloudflared | 🔲 Planned |
| 3 | launchd Services | 🔲 Planned |
| 4 | Health Checks | 🔲 Planned |
| 4 | Logs | 🔲 Planned |
| 4 | Alerts | 🔲 Planned |
| 5 | Scheduler | 🔲 Planned |
| 5 | Database Metrics | 🔲 Planned |
| 5 | Historical Metrics | 🔲 Planned |
| — | HexaMonitor Dashboard | 🔲 Separate Project |

---

## License

Internal project — not for public distribution.
