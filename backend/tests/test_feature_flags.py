"""
Unit tests for HexaAgent feature flags (ENABLE_OPERATIONS_POLLER and ENABLE_LOG_PUSHER).
"""

import asyncio
from unittest import TestCase
from unittest.mock import AsyncMock, patch

from app.core.config import get_settings
from app.main import app, lifespan


class TestFeatureFlags(TestCase):

    def setUp(self):
        self.settings = get_settings()

    def test_feature_flags_default_values(self):
        """Test default values of feature flags are False."""
        self.assertFalse(self.settings.ENABLE_OPERATIONS_POLLER)
        self.assertFalse(self.settings.ENABLE_LOG_PUSHER)

    @patch("app.main.snapshot_manager")
    @patch("app.main.snapshot_pusher")
    @patch("app.main.reporter")
    @patch("app.main.queue_manager")
    @patch("app.main.history_engine")
    @patch("app.main.operations_poller")
    @patch("app.main.log_pusher")
    def test_lifespan_feature_flags_disabled(
        self,
        mock_log_pusher,
        mock_ops_poller,
        mock_history,
        mock_queue,
        mock_reporter,
        mock_sn_pusher,
        mock_sn_manager,
    ):
        """Test background services operations_poller and log_pusher do NOT start when flags are False."""
        self.settings.ENABLE_OPERATIONS_POLLER = False
        self.settings.ENABLE_LOG_PUSHER = False

        # Setup async stop mocks
        mock_sn_manager.stop = AsyncMock()
        mock_sn_pusher.stop = AsyncMock()
        mock_reporter.stop = AsyncMock()
        mock_queue.stop_worker = AsyncMock()
        mock_history.stop = AsyncMock()
        mock_ops_poller.stop = AsyncMock()
        mock_log_pusher.stop = AsyncMock()

        async def run_lifespan():
            async with lifespan(app):
                pass

        asyncio.run(run_lifespan())

        # Verify start/stop were NOT called for disabled services
        mock_ops_poller.start.assert_not_called()
        mock_log_pusher.start.assert_not_called()
        mock_ops_poller.stop.assert_not_called()
        mock_log_pusher.stop.assert_not_called()

        # Verify enabled services WERE started and stopped
        mock_sn_manager.start.assert_called_once()
        mock_sn_pusher.start.assert_called_once()

    @patch("app.main.snapshot_manager")
    @patch("app.main.snapshot_pusher")
    @patch("app.main.reporter")
    @patch("app.main.queue_manager")
    @patch("app.main.history_engine")
    @patch("app.main.operations_poller")
    @patch("app.main.log_pusher")
    def test_lifespan_feature_flags_enabled(
        self,
        mock_log_pusher,
        mock_ops_poller,
        mock_history,
        mock_queue,
        mock_reporter,
        mock_sn_pusher,
        mock_sn_manager,
    ):
        """Test background services operations_poller and log_pusher START when flags are True."""
        self.settings.ENABLE_OPERATIONS_POLLER = True
        self.settings.ENABLE_LOG_PUSHER = True

        mock_sn_manager.stop = AsyncMock()
        mock_sn_pusher.stop = AsyncMock()
        mock_reporter.stop = AsyncMock()
        mock_queue.stop_worker = AsyncMock()
        mock_history.stop = AsyncMock()
        mock_ops_poller.stop = AsyncMock()
        mock_log_pusher.stop = AsyncMock()

        async def run_lifespan():
            async with lifespan(app):
                pass

        asyncio.run(run_lifespan())

        # Verify start/stop WERE called when flags are enabled
        mock_ops_poller.start.assert_called_once()
        mock_log_pusher.start.assert_called_once()
        mock_ops_poller.stop.assert_called_once()
        mock_log_pusher.stop.assert_called_once()

        # Reset flags to safe default False after test
        self.settings.ENABLE_OPERATIONS_POLLER = False
        self.settings.ENABLE_LOG_PUSHER = False
