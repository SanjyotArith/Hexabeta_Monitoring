"""
HexaAgent — Operations Engine (Phase 2B).

Includes Operations Registry, Validation Engine, Operation Queue,
Execution Engine, and Audit Logger.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.core.config import get_settings
from app.core.maintenance import maintenance_manager

logger = logging.getLogger("hexa_agent.operations")

# Map of service and action to the default macOS commands.
# Templates support formatting if needed.
COMMANDS_REGISTRY: dict[str, dict[str, str]] = {
    "backend": {
        "start": "launchctl load -w {backend_plist}",
        "stop": "launchctl unload {backend_plist}",
        "restart": "launchctl unload {backend_plist} && launchctl load -w {backend_plist}",
    },
    "postgres": {
        "start": "brew services start {postgres_service}",
        "stop": "brew services stop {postgres_service}",
        "restart": "brew services restart {postgres_service}",
    },
    "redis": {
        "start": "brew services start {redis_service}",
        "stop": "brew services stop {redis_service}",
        "restart": "brew services restart {redis_service}",
    },
    "nginx": {
        "start": "sudo launchctl load -w {nginx_plist}",
        "stop": "sudo launchctl unload {nginx_plist}",
        "restart": "sudo launchctl unload {nginx_plist} && sudo launchctl load -w {nginx_plist}",
    },
    "cloudflared": {
        "start": "launchctl load -w {cloudflared_plist}",
        "stop": "launchctl unload {cloudflared_plist}",
        "restart": "launchctl unload {cloudflared_plist} && launchctl load -w {cloudflared_plist}",
    },
    "deploy": {
        "dry_run": "{deploy_script} --dry-run",
        "execute": "{deploy_script}",
    },
}


class AuditLogger:
    """Manages persistence of operational audit records using the history database."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS audit_logs (
                        id TEXT PRIMARY KEY,
                        service TEXT NOT NULL,
                        operation TEXT NOT NULL,
                        requested_time TEXT NOT NULL,
                        started_time TEXT,
                        completed_time TEXT,
                        duration REAL,
                        status TEXT NOT NULL,
                        executed_command TEXT,
                        exit_code INTEGER,
                        output TEXT,
                        error TEXT,
                        mode TEXT NOT NULL
                    )
                    """
                )
                conn.commit()
        except Exception as e:
            logger.exception("Failed to initialize audit database table: %s", e)

    def log_operation(self, op: dict[str, Any]) -> None:
        """Insert or replace an operation record in the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO audit_logs (
                        id, service, operation, requested_time, started_time,
                        completed_time, duration, status, executed_command,
                        exit_code, output, error, mode
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        op["id"],
                        op["service"],
                        op["operation"],
                        op["requested_time"],
                        op.get("started_time"),
                        op.get("completed_time"),
                        op.get("duration"),
                        op["status"],
                        op.get("executed_command"),
                        op.get("exit_code"),
                        op.get("output"),
                        op.get("error"),
                        op["mode"],
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.error("Failed to write audit log to database: %s", e)

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Retrieve execution history, ordered by start time descending."""
        history = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT * FROM audit_logs ORDER BY requested_time DESC LIMIT ?",
                    (limit,),
                )
                for row in cursor.fetchall():
                    history.append(dict(row))
        except Exception as e:
            logger.error("Failed to retrieve audit log history: %s", e)
        return history

    def get_latest_record(self) -> Optional[dict[str, Any]]:
        """Get details of the last run/running operation."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT * FROM audit_logs ORDER BY requested_time DESC LIMIT 1"
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception:
            return None


class ValidationEngine:
    """Performs validation checks on services before running operations."""

    @staticmethod
    def validate(service: str, operation: str) -> tuple[bool, list[str]]:
        """
        Validate whether a service operation is safe to proceed.

        Returns (is_valid, list_of_errors).
        """
        service = service.strip().lower()
        operation = operation.strip().lower()
        settings = get_settings()
        errors: list[str] = []

        # Global command existence check helper
        def has_cmd(cmd: str) -> bool:
            return shutil.which(cmd) is not None

        # Check launchctl plist helper
        def plist_exists(plist_path: str) -> bool:
            return Path(plist_path).exists()

        if service == "backend":
            plist_path = f"/Users/hexabeta/Library/LaunchAgents/{settings.BACKEND_LAUNCH_LABEL}.plist"
            if not plist_exists(plist_path) and not plist_exists(f"/Library/LaunchAgents/{settings.BACKEND_LAUNCH_LABEL}.plist"):
                errors.append(f"Backend LaunchAgent plist for '{settings.BACKEND_LAUNCH_LABEL}' not found")

        elif service == "postgres":
            if not has_cmd("brew"):
                errors.append("Homebrew (brew) executable not found in PATH")

        elif service == "redis":
            if not has_cmd("brew") and not has_cmd("redis-server"):
                errors.append("Neither brew nor redis-server found in PATH")

        elif service == "nginx":
            plist_path = f"/Library/LaunchDaemons/{settings.NGINX_LABEL}.plist"
            if not plist_exists(plist_path) and not plist_exists(f"/Users/hexabeta/Library/LaunchDaemons/{settings.NGINX_LABEL}.plist"):
                errors.append(f"Nginx LaunchDaemon plist for '{settings.NGINX_LABEL}' not found")

        elif service == "cloudflared":
            if not has_cmd("cloudflared"):
                errors.append("cloudflared command not found in PATH")

        elif service == "deploy":
            script = settings.DEPLOY_SCRIPT
            if not script or not Path(script).exists():
                errors.append(f"Deployment script '{script}' does not exist")
            elif not os.access(script, os.X_OK):
                errors.append(f"Deployment script '{script}' is not executable")
            
            git_path = settings.git_project_path_resolved
            if not git_path.exists():
                errors.append(f"Git project path '{git_path}' does not exist")
            elif not (git_path / ".git").exists():
                errors.append(f"Path '{git_path}' is not a valid Git repository")

        else:
            errors.append(f"Unknown service: {service}")

        return len(errors) == 0, errors


class OperationQueueManager:
    """Manages the operational queue, executing commands in order."""

    def __init__(self, audit_logger: AuditLogger) -> None:
        self.audit_logger = audit_logger
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._active_op: Optional[dict[str, Any]] = None
        self._pending_ops: list[dict[str, Any]] = []
        self._worker_task: Optional[asyncio.Task] = None

    def get_queue_status(self) -> dict[str, Any]:
        """Return the current running and pending operations in queue."""
        return {
            "active": self._active_op,
            "pending": self._pending_ops,
            "pending_count": len(self._pending_ops),
        }

    def start_worker(self) -> None:
        """Start the background queue execution worker."""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._queue_worker())

    async def stop_worker(self) -> None:
        """Cancel the background queue worker cleanly."""
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("Operation queue worker stopped.")

    def submit(
        self,
        service: str,
        operation: str,
        mode: str = "production",
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Create and queue a new operation task.

        Returns the initial operation metadata.
        """
        service = service.strip().lower()
        operation = operation.strip().lower()
        op_id = str(uuid.uuid4())
        op = {
            "id": op_id,
            "service": service,
            "operation": operation,
            "requested_time": datetime.now(timezone.utc).isoformat(),
            "started_time": None,
            "completed_time": None,
            "duration": None,
            "status": "pending",
            "executed_command": None,
            "exit_code": None,
            "output": "",
            "error": None,
            "mode": mode,
            "params": params or {},
        }
        self._pending_ops.append(op)
        self.audit_logger.log_operation(op)
        self._queue.put_nowait(op)
        return op

    def cancel_operation(self, op_id: str) -> bool:
        """Cancel a pending operation by ID."""
        for op in list(self._pending_ops):
            if op["id"] == op_id:
                self._pending_ops.remove(op)
                op["status"] = "cancelled"
                op["completed_time"] = datetime.now(timezone.utc).isoformat()
                self.audit_logger.log_operation(op)
                # Note: If it's already in the queue, the worker will skip it.
                return True
        return False

    async def _queue_worker(self) -> None:
        """Processes submitted operations sequentially from the queue."""
        logger.info("Operation queue worker started.")
        while True:
            try:
                op = await self._queue.get()
            except asyncio.CancelledError:
                break

            # If task was cancelled while pending in queue, skip it
            if op["id"] not in [p["id"] for p in self._pending_ops] and op["status"] == "cancelled":
                self._queue.task_done()
                continue

            # Remove from pending, set to active
            if op in self._pending_ops:
                self._pending_ops.remove(op)
            self._active_op = op

            try:
                await self._execute_op(op)
            except Exception as e:
                logger.exception("Error executing operation %s: %s", op["id"], e)
                op["status"] = "failed"
                op["error"] = str(e)
                op["completed_time"] = datetime.now(timezone.utc).isoformat()
                self.audit_logger.log_operation(op)
            finally:
                self._active_op = None
                self._queue.task_done()

                # Trigger an immediate refresh of the Snapshot Engine
                from app.core.snapshot import snapshot_manager
                await snapshot_manager._refresh()

    async def _execute_op(self, op: dict[str, Any]) -> None:
        """Resolve command, validate, check dry-run, execute, and record results."""
        op["status"] = "running"
        op["started_time"] = datetime.now(timezone.utc).isoformat()
        self.audit_logger.log_operation(op)

        service = op["service"].strip().lower()
        action = op["operation"].strip().lower()
        settings = get_settings()

        # Step 1: Pre-execution validation
        is_valid, errors = ValidationEngine.validate(service, action)
        if not is_valid:
            op["status"] = "failed"
            op["error"] = f"Validation failed: {'; '.join(errors)}"
            op["completed_time"] = datetime.now(timezone.utc).isoformat()
            self.audit_logger.log_operation(op)
            logger.error(
                "Operation validation failed: service=%s operation=%s errors=%s",
                service,
                action,
                "; ".join(errors),
            )
            return

        # Resolve command template
        cmd_templates = COMMANDS_REGISTRY.get(service)
        if not cmd_templates or action not in cmd_templates:
            op["status"] = "failed"
            op["error"] = f"Operation '{action}' not configured for service '{service}'"
            op["completed_time"] = datetime.now(timezone.utc).isoformat()
            self.audit_logger.log_operation(op)
            logger.error(
                "Operation registry lookup failed: service=%s operation=%s",
                service,
                action,
            )
            return

        # Plist/Script references formatting
        backend_plist = f"/Users/hexabeta/Library/LaunchAgents/{settings.BACKEND_LAUNCH_LABEL}.plist"
        if not Path(backend_plist).exists():
            backend_plist = f"/Library/LaunchAgents/{settings.BACKEND_LAUNCH_LABEL}.plist"
            
        nginx_plist = f"/Library/LaunchDaemons/{settings.NGINX_LABEL}.plist"
        if not Path(nginx_plist).exists():
            nginx_plist = f"/Users/hexabeta/Library/LaunchDaemons/{settings.NGINX_LABEL}.plist"

        cloudflared_plists = [
            "/Users/hexabeta/Library/LaunchAgents/homebrew.mxcl.cloudflared.plist",
            "/Users/hexabeta/Library/LaunchAgents/com.oring.cloudflared.plist",
            "/Library/LaunchDaemons/com.cloudflare.cloudflared.plist",
            "/Users/hexabeta/Library/LaunchAgents/com.cloudflare.tunnel.plist",
            "/Library/LaunchAgents/com.cloudflare.tunnel.plist",
        ]
        cloudflared_plist = cloudflared_plists[0]
        for p in cloudflared_plists:
            if Path(p).exists():
                cloudflared_plist = p
                break

        cmd_format = {
            "backend_plist": backend_plist,
            "postgres_service": settings.POSTGRES_SERVICE,
            "redis_service": settings.REDIS_SERVICE,
            "nginx_plist": nginx_plist,
            "cloudflared_plist": cloudflared_plist,
            "deploy_script": settings.DEPLOY_SCRIPT,
        }

        command = cmd_templates[action].format(**cmd_format)
        op["executed_command"] = command
        self.audit_logger.log_operation(op)

        # Handle Dry-Run Mode
        if op["mode"] == "dry_run":
            op["status"] = "completed"
            op["output"] = f"[DRY RUN] Would execute command: {command}"
            op["exit_code"] = 0
            op["completed_time"] = datetime.now(timezone.utc).isoformat()
            op["duration"] = 0.0
            self.audit_logger.log_operation(op)
            return

        # Enable Maintenance Mode automatically for deployment execution
        is_deploy = (service == "deploy" and action == "execute")
        if is_deploy:
            maintenance_manager.enable()

        # Run process
        t_start = time.monotonic()
        logger.info(
            "Executing operation: service=%s operation=%s command=%s",
            service,
            action,
            command,
        )
        try:
            # We run commands in a subshell since they use plists, sudo, or brew services
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            duration = time.monotonic() - t_start
            
            output = stdout.decode().strip()
            err_out = stderr.decode().strip()
            
            op["exit_code"] = process.returncode
            op["duration"] = round(duration, 2)
            op["output"] = output + ("\n" + err_out if err_out else "")
            
            if process.returncode == 0:
                op["status"] = "completed"
                logger.info(
                    "Operation completed: status=%s exit_code=%s duration=%s",
                    op["status"],
                    op["exit_code"],
                    op["duration"],
                )
            else:
                op["status"] = "failed"
                op["error"] = err_out or f"Shell command returned non-zero exit code: {process.returncode}"
                logger.error(
                    "Operation failed: service=%s operation=%s command=%s exit_code=%s stdout=%s stderr=%s",
                    service,
                    action,
                    command,
                    process.returncode,
                    output,
                    err_out,
                )
                
        except Exception as e:
            op["status"] = "failed"
            op["error"] = str(e)
            op["duration"] = round(time.monotonic() - t_start, 2)
            logger.exception(
                "Operation raised exception: service=%s operation=%s command=%s error=%s",
                service,
                action,
                command,
                str(e),
            )
            
        finally:
            # Disable Maintenance Mode automatically after deployment verification/execution finishes
            if is_deploy:
                # We can perform a quick sleep or wait for services to come back before disabling
                await asyncio.sleep(2)
                maintenance_manager.disable()

            op["completed_time"] = datetime.now(timezone.utc).isoformat()
            self.audit_logger.log_operation(op)


class ConfirmationManager:
    """Manages short-lived double confirmation tokens for high-risk operations."""

    def __init__(self) -> None:
        # Maps token -> confirmation dict
        self._tokens: dict[str, dict[str, Any]] = {}
        self._ttl = 300  # 5 minutes in seconds

    def generate_token(self, service: str, operation: str, mode: str) -> str:
        """Create a new confirmation session and return the token identifier."""
        # Cleanup expired tokens first
        self.cleanup()

        service = service.strip().lower()
        operation = operation.strip().lower()

        token = str(uuid.uuid4())
        phrase = "DEPLOY" if service == "deploy" else "RESTART"
        
        self._tokens[token] = {
            "service": service,
            "operation": operation,
            "mode": mode,
            "phrase": phrase,
            "created_at": time.time(),
        }
        return token

    def verify_and_claim(self, token: str, phrase: str) -> Optional[dict[str, Any]]:
        """Verify the phrase matches the session and return the operation dict."""
        self.cleanup()
        session = self._tokens.get(token)
        if not session:
            return None

        if session["phrase"].strip().upper() == phrase.strip().upper():
            # Claim the token (remove it from pool)
            return self._tokens.pop(token)
            
        return None

    def cleanup(self) -> None:
        """Removes expired confirmation sessions from state."""
        now = time.time()
        expired = [
            t for t, data in self._tokens.items()
            if now - data["created_at"] > self._ttl
        ]
        for t in expired:
            self._tokens.pop(t, None)


# Instantiate Singletons using common HistoryDB path
db_path = Path(__file__).resolve().parent.parent.parent / "data" / "history.db"
audit_logger = AuditLogger(db_path)
queue_manager = OperationQueueManager(audit_logger)
confirmation_manager = ConfirmationManager()
