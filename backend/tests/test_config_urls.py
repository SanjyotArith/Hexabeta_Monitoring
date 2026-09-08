"""
Unit tests for URL construction in app.core.config.
"""

import unittest
from unittest.mock import MagicMock

from app.core.config import Settings


class TestConfigUrls(unittest.TestCase):
    def test_normal_configuration(self):
        settings = Settings(
            HEXABETA_PROJECT_ROOT="/tmp",
            HEXABETA_BACKEND_PATH="/tmp/backend",
            HEXABETA_FRONTEND_PATH="/tmp/frontend",
            HEXABETA_UPLOADS_PATH="/tmp/uploads",
            MONITOR_URL="http://100.65.232.22:8000",
            API_PREFIX="/api/v1",
            SNAPSHOT_PUSH_ENDPOINT="/snapshot/push",
        )
        self.assertEqual(
            settings.full_snapshot_push_url,
            "http://100.65.232.22:8000/api/v1/snapshot/push",
        )

    def test_monitor_url_already_has_api_v1(self):
        settings = Settings(
            HEXABETA_PROJECT_ROOT="/tmp",
            HEXABETA_BACKEND_PATH="/tmp/backend",
            HEXABETA_FRONTEND_PATH="/tmp/frontend",
            HEXABETA_UPLOADS_PATH="/tmp/uploads",
            MONITOR_URL="http://100.65.232.22:8000/api/v1",
            API_PREFIX="/api/v1",
            SNAPSHOT_PUSH_ENDPOINT="/snapshot/push",
        )
        self.assertEqual(
            settings.full_snapshot_push_url,
            "http://100.65.232.22:8000/api/v1/snapshot/push",
        )

    def test_endpoint_already_has_api_v1(self):
        settings = Settings(
            HEXABETA_PROJECT_ROOT="/tmp",
            HEXABETA_BACKEND_PATH="/tmp/backend",
            HEXABETA_FRONTEND_PATH="/tmp/frontend",
            HEXABETA_UPLOADS_PATH="/tmp/uploads",
            MONITOR_URL="http://100.65.232.22:8000",
            API_PREFIX="/api/v1",
            SNAPSHOT_PUSH_ENDPOINT="/api/v1/snapshot/push",
        )
        self.assertEqual(
            settings.full_snapshot_push_url,
            "http://100.65.232.22:8000/api/v1/snapshot/push",
        )

    def test_slash_variations(self):
        settings = Settings(
            HEXABETA_PROJECT_ROOT="/tmp",
            HEXABETA_BACKEND_PATH="/tmp/backend",
            HEXABETA_FRONTEND_PATH="/tmp/frontend",
            HEXABETA_UPLOADS_PATH="/tmp/uploads",
            MONITOR_URL="http://100.65.232.22:8000/",
            API_PREFIX="api/v1/",
            SNAPSHOT_PUSH_ENDPOINT="snapshot/push",
        )
        self.assertEqual(
            settings.full_snapshot_push_url,
            "http://100.65.232.22:8000/api/v1/snapshot/push",
        )

    def test_all_endpoints(self):
        settings = Settings(
            HEXABETA_PROJECT_ROOT="/tmp",
            HEXABETA_BACKEND_PATH="/tmp/backend",
            HEXABETA_FRONTEND_PATH="/tmp/frontend",
            HEXABETA_UPLOADS_PATH="/tmp/uploads",
            MONITOR_URL="http://100.65.232.22:8000",
            API_PREFIX="/api/v1",
            REPORT_ENDPOINT="/agents/report",
            SNAPSHOT_PUSH_ENDPOINT="/snapshot/push",
            LOGS_PUSH_ENDPOINT="/logs/push",
            OPERATIONS_POLL_ENDPOINT="/operations/pending",
        )
        self.assertEqual(
            settings.full_report_url,
            "http://100.65.232.22:8000/api/v1/agents/report",
        )
        self.assertEqual(
            settings.full_snapshot_push_url,
            "http://100.65.232.22:8000/api/v1/snapshot/push",
        )
        self.assertEqual(
            settings.full_logs_push_url,
            "http://100.65.232.22:8000/api/v1/logs/push",
        )
        self.assertEqual(
            settings.full_operations_poll_url,
            "http://100.65.232.22:8000/api/v1/operations/pending",
        )


if __name__ == "__main__":
    unittest.main()
