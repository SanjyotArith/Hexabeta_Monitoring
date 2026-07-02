"""
HexaAgent — HexaBeta Process Finder.

Shared utility used by CPU and Memory collectors to locate
uvicorn processes that belong to the HexaBeta backend.
"""

from __future__ import annotations

import logging
from typing import Optional

import psutil

from app.core.config import Settings

logger = logging.getLogger("hexa_agent.process_finder")


def find_hexabeta_processes(settings: Settings) -> list[psutil.Process]:
    """
    Discover all uvicorn processes that belong to the HexaBeta backend.

    Matching criteria (must satisfy ALL of the following):
        1. The process command-line contains ``uvicorn``.
        2. The process command-line references the configured backend path
           **or** the process is listening on ``HEXABETA_BACKEND_PORT``.

    Once the main process is found, all of its child (worker) processes
    are automatically included.

    Returns
    -------
    list[psutil.Process]
        Main process + worker processes. Empty list if none found.
    """
    backend_path: str = settings.HEXABETA_BACKEND_PATH
    backend_port: int = settings.HEXABETA_BACKEND_PORT

    main_process: Optional[psutil.Process] = None

    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline: list[str] = proc.info.get("cmdline") or []
            cmdline_str: str = " ".join(cmdline)

            # Criterion 1 — must be a uvicorn process
            if "uvicorn" not in cmdline_str:
                continue

            # Criterion 2a — cmdline references the backend path
            if backend_path in cmdline_str:
                main_process = proc
                break

            # Criterion 2b — process listens on the configured port
            if _listens_on_port(proc, backend_port):
                main_process = proc
                break

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    if main_process is None:
        logger.debug("No HexaBeta uvicorn process found")
        return []

    # Collect main process + all child workers
    processes: list[psutil.Process] = [main_process]
    try:
        children = main_process.children(recursive=True)
        processes.extend(children)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    logger.debug(
        "Found HexaBeta processes: main PID %d + %d workers",
        main_process.pid,
        len(processes) - 1,
    )
    return processes


def _listens_on_port(proc: psutil.Process, port: int) -> bool:
    """Return True if *proc* has a listening socket on *port*."""
    try:
        for conn in proc.net_connections(kind="inet"):
            if conn.status == psutil.CONN_LISTEN and conn.laddr.port == port:
                return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass
    return False
