from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1 import auth, api_checks, agent_ingest, infrastructure
from app.services.scheduler_service import start_scheduler, shutdown_scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup tasks
    start_scheduler()
    yield
    # Shutdown tasks
    shutdown_scheduler()

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="HexaMonitor Core API platform specifically tailored for HexaBeta infrastructure.",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
    lifespan=lifespan
)

# CORS configurations (allows any local port for development/testing)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Authentication Router
app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["Authentication"])

# Include Synthetic Monitoring Router
app.include_router(api_checks.router, prefix=f"{settings.API_V1_STR}/api-checks", tags=["Synthetic Monitoring"])

# Include Agent Telemetry Ingest Router
app.include_router(agent_ingest.router, prefix=f"{settings.API_V1_STR}/agent/ingest", tags=["Agent Ingestion"])

# Include Infrastructure Router
app.include_router(infrastructure.router, prefix=f"{settings.API_V1_STR}", tags=["Infrastructure"])

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy"
    }

# Serve Frontend Static Files
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

frontend_dist_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
)

assets_dir = os.path.join(frontend_dist_dir, "assets")
if os.path.exists(assets_dir):
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

@app.get("/{catchall:path}")
async def serve_spa(catchall: str):
    if catchall.startswith("api/") or catchall.startswith("docs") or catchall.startswith("redoc") or catchall.startswith("openapi.json"):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not Found")
        
    file_path = os.path.join(frontend_dist_dir, catchall)
    if catchall and os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)
        
    index_path = os.path.join(frontend_dist_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
        
    return {
        "status": "warning",
        "message": "Frontend build files not found. Please build the frontend by running 'npm run build' inside the frontend directory."
    }
