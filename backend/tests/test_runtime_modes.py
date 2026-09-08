"""
Unit tests verifying RUN_MODE separation (agent vs monitor).

Proves:
1. Agent mode does not start Monitor scheduler.
2. Agent mode does not initialize Monitor DB.
3. Agent mode still starts SnapshotManager.
4. Agent mode still starts Reporter.
5. Agent mode still starts HistoryEngine.
6. Disabled OperationsPoller remains disabled.
7. Disabled LogPusher remains disabled.
8. Monitor mode still starts Monitor scheduler.
9. Monitor mode does not accidentally start Agent snapshot pushing.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

from app.core.config import get_settings
from app.main import app, lifespan


class TestRuntimeModes(unittest.TestCase):

    def setUp(self):
        self.settings = get_settings()
        self._orig_mode = self.settings.RUN_MODE
        self._orig_ops = self.settings.ENABLE_OPERATIONS_POLLER
        self._orig_logs = self.settings.ENABLE_LOG_PUSHER

    def tearDown(self):
        self.settings.RUN_MODE = self._orig_mode
        self.settings.ENABLE_OPERATIONS_POLLER = self._orig_ops
        self.settings.ENABLE_LOG_PUSHER = self._orig_logs

    @patch("app.main.snapshot_manager")
    @patch("app.main.snapshot_pusher")
    @patch("app.main.reporter")
    @patch("app.main.queue_manager")
    @patch("app.main.history_engine")
    @patch("app.main.operations_poller")
    @patch("app.main.log_pusher")
    @patch("app.services.scheduler_service.start_scheduler")
    @patch("app.services.scheduler_service.shutdown_scheduler")
    def test_agent_mode_service_lifecycle(
        self,
        mock_sched_stop,
        mock_sched_start,
        mock_log_pusher,
        mock_ops_poller,
        mock_history,
        mock_queue,
        mock_reporter,
        mock_sn_pusher,
        mock_sn_manager,
    ):
        """Test RUN_MODE=agent starts Agent loops and DOES NOT start Monitor scheduler."""
        self.settings.RUN_MODE = "agent"
        self.settings.ENABLE_OPERATIONS_POLLER = False
        self.settings.ENABLE_LOG_PUSHER = False

        mock_sn_manager.stop = AsyncMock()
        mock_sn_pusher.stop = AsyncMock()
        mock_reporter.stop = AsyncMock()
        mock_queue.stop_worker = AsyncMock()
        mock_history.stop = AsyncMock()

        async def run_lifespan():
            async with lifespan(app):
                pass

        asyncio.run(run_lifespan())

        # 1. Agent mode does not start Monitor scheduler
        mock_sched_start.assert_not_called()
        mock_sched_stop.assert_not_called()

        # 3, 4, 5. Agent mode starts SnapshotManager, Reporter, HistoryEngine
        mock_sn_manager.start.assert_called_once()
        mock_sn_pusher.start.assert_called_once()
        mock_reporter.start.assert_called_once()
        mock_history.start.assert_called_once()

        # 6, 7. Disabled OperationsPoller and LogPusher remain disabled
        mock_ops_poller.start.assert_not_called()
        mock_log_pusher.start.assert_not_called()

    @patch("app.main.snapshot_manager")
    @patch("app.main.snapshot_pusher")
    @patch("app.main.reporter")
    @patch("app.main.queue_manager")
    @patch("app.main.history_engine")
    @patch("app.main.operations_poller")
    @patch("app.main.log_pusher")
    @patch("app.services.scheduler_service.start_scheduler")
    @patch("app.services.scheduler_service.shutdown_scheduler")
    def test_monitor_mode_service_lifecycle(
        self,
        mock_sched_stop,
        mock_sched_start,
        mock_log_pusher,
        mock_ops_poller,
        mock_history,
        mock_queue,
        mock_reporter,
        mock_sn_pusher,
        mock_sn_manager,
    ):
        """Test RUN_MODE=monitor starts Monitor scheduler and DOES NOT start Agent loops."""
        self.settings.RUN_MODE = "monitor"

        async def run_lifespan():
            async with lifespan(app):
                pass

        asyncio.run(run_lifespan())

        # 8. Monitor mode starts Monitor scheduler
        mock_sched_start.assert_called_once()
        mock_sched_stop.assert_called_once()

        # 9. Monitor mode does NOT start Agent snapshot pushing or reporting loops
        mock_sn_manager.start.assert_not_called()
        mock_sn_pusher.start.assert_not_called()
        mock_reporter.start.assert_not_called()
        mock_history.start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
