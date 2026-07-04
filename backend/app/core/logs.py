"""
HexaAgent — Logs Engine (Phase 2B).

Reads, tails, and filters log files for configured services in a safe,
read-only manner.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Generator, Optional

from app.core.config import get_settings

logger = logging.getLogger("hexa_agent.logs")


def get_log_path(service: str) -> Optional[Path]:
    """Get the path to the log file for a given service."""
    settings = get_settings()
    mapping = {
        "backend": settings.BACKEND_LOG_PATH,
        "backend_error": settings.BACKEND_ERROR_LOG_PATH,
        "nginx": settings.NGINX_LOG_PATH,
        "nginx_error": settings.NGINX_ERROR_LOG_PATH,
        "redis": settings.REDIS_LOG_PATH,
        "postgres": settings.POSTGRES_LOG_PATH,
        "cloudflared": settings.CLOUDFLARED_LOG_PATH,
        "deployment": settings.DEPLOYMENT_LOG_PATH,
    }
    
    path_str = mapping.get(service)
    if not path_str:
        return None
        
    path = Path(path_str)
    try:
        if path.exists() and path.is_dir():
            # Automatically find the most recently modified .log file in the directory
            log_files = list(path.glob("*.log"))
            if not log_files:
                logger.warning("No log files found in directory: %s", path)
                return None
            log_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return log_files[0]
    except Exception as e:
        logger.error("Failed to check directory path for service '%s': %s", service, e)
        return None

    return path


def read_logs_tail(
    service: str,
    tail_lines: int = 100,
    search_query: Optional[str] = None
) -> list[str]:
    """
    Read the end of a log file for a service, optionally filtering by search_query.

    Parameters
    ----------
    service : str
        The service name key.
    tail_lines : int
        Maximum number of matched lines to return.
    search_query : str, optional
        A search query or regular expression to filter log lines.

    Returns
    -------
    list[str]
        List of matching log lines.
    """
    log_path = get_log_path(service)
    if not log_path or not log_path.exists():
        logger.warning("Log file not found or not configured for service '%s': %s", service, log_path)
        return [f"Error: Log file not found or configured for service '{service}'"]

    matched_lines: list[str] = []
    compiled_regex: Optional[re.Pattern] = None

    if search_query:
        try:
            compiled_regex = re.compile(search_query, re.IGNORECASE)
        except re.error:
            # Fallback to simple substring match
            pass

    # Read from end of file to save memory
    buffer_size = 8192
    try:
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            file_size = f.tell()
            position = file_size
            remainder = b""
            
            while position > 0 and len(matched_lines) < tail_lines:
                read_size = min(buffer_size, position)
                position -= read_size
                f.seek(position)
                chunk = f.read(read_size) + remainder
                
                # Split lines
                lines = chunk.split(b"\n")
                # Keep first element as remainder for next chunk (it might be incomplete)
                remainder = lines[0]
                lines = lines[1:]
                
                # Process lines from last to first
                for raw_line in reversed(lines):
                    try:
                        line = raw_line.decode("utf-8").strip()
                    except UnicodeDecodeError:
                        continue
                    
                    if not line:
                        continue

                    # Apply search filter
                    if compiled_regex:
                        if compiled_regex.search(line):
                            matched_lines.append(line)
                    elif search_query:
                        if search_query.lower() in line.lower():
                            matched_lines.append(line)
                    else:
                        matched_lines.append(line)

                    if len(matched_lines) >= tail_lines:
                        break

            # Handle first line/remainder if we haven't reached tail_lines limit
            if remainder and len(matched_lines) < tail_lines:
                try:
                    line = remainder.decode("utf-8").strip()
                    if line:
                        if compiled_regex:
                            if compiled_regex.search(line):
                                matched_lines.append(line)
                        elif search_query:
                            if search_query.lower() in line.lower():
                                matched_lines.append(line)
                        else:
                            matched_lines.append(line)
                except UnicodeDecodeError:
                    pass

    except Exception as e:
        logger.exception("Failed to read log file for '%s': %s", service, e)
        return [f"Error: Failed to read log file: {e}"]

    # We read backwards, so reverse to restore chronological order
    return list(reversed(matched_lines))
