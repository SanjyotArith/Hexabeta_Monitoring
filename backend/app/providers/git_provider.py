"""
HexaAgent — Git Provider (Phase 2A).

Collects Git repository information for the HexaBeta project.
All commands are READ ONLY — nothing is modified.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.config import get_settings
from app.core.registry import BaseCollector

logger = logging.getLogger("hexa_agent.providers.git")


class GitProvider(BaseCollector):
    """Collect Git repository status for HexaBeta (read-only)."""

    @property
    def name(self) -> str:
        return "git"

    async def collect(self) -> dict[str, Any]:
        settings = get_settings()
        git_path = str(settings.git_project_path_resolved)

        result: dict[str, Any] = {
            "branch": None,
            "commit_sha": None,
            "remote": None,
            "working_tree_clean": None,
            "untracked_files_count": None,
            "last_commit_message": None,
            "last_commit_time": None,
            "last_checked": datetime.now(timezone.utc).isoformat(),
            "error": None,
        }

        try:
            # Run all git commands concurrently
            (
                branch,
                commit_sha,
                remote,
                status_output,
                last_message,
                last_time,
            ) = await asyncio.gather(
                _git_cmd(git_path, "rev-parse", "--abbrev-ref", "HEAD"),
                _git_cmd(git_path, "rev-parse", "HEAD"),
                _git_cmd(git_path, "remote", "get-url", "origin"),
                _git_cmd(git_path, "status", "--porcelain"),
                _git_cmd(git_path, "log", "-1", "--format=%s"),
                _git_cmd(git_path, "log", "-1", "--format=%aI"),
            )

            result["branch"] = branch
            result["commit_sha"] = commit_sha
            result["remote"] = remote
            result["last_commit_message"] = last_message
            result["last_commit_time"] = last_time

            # Parse status
            if status_output is not None:
                lines = [l for l in status_output.splitlines() if l.strip()]
                result["working_tree_clean"] = len(lines) == 0
                untracked = [l for l in lines if l.startswith("??")]
                result["untracked_files_count"] = len(untracked)
            else:
                result["working_tree_clean"] = None
                result["untracked_files_count"] = None

        except Exception as e:
            logger.exception("Git provider error: %s", e)
            result["error"] = str(e)

        return result


async def _git_cmd(cwd: str, *args: str) -> Optional[str]:
    """
    Run a git command in the given directory and return stdout.

    Returns None if the command fails.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)

        if process.returncode == 0:
            return stdout.decode().strip()
    except (FileNotFoundError, asyncio.TimeoutError):
        pass

    return None
