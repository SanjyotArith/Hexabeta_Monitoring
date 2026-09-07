"""
Unit tests for PostgresProvider (Host mode, Docker mode, Auto mode, POSTGRES_MODE configuration).
"""

import asyncio
from unittest import TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.config import get_settings
from app.providers.postgres import PostgresProvider, _test_connection
from app.utils.docker import DockerStatus


class TestPostgresProvider(TestCase):

    def setUp(self):
        self.settings = get_settings()
        self.settings.POSTGRES_MODE = "auto"
        self.provider = PostgresProvider()

    @patch("app.providers.postgres.check_brew_service")
    @patch("app.providers.postgres.find_process_by_name")
    @patch("app.providers.postgres.get_process_metrics")
    @patch("app.providers.postgres._test_connection")
    def test_postgres_host_mode(self, mock_test_conn, mock_metrics, mock_find_proc, mock_check_brew):
        """Test PostgreSQL host process detection (host mode & auto mode with host process present)."""
        self.settings.POSTGRES_MODE = "host"
        mock_check_brew.return_value = {"running": True, "pid": 1234}
        mock_metrics.return_value = {
            "cpu_percent": 2.5,
            "memory_bytes": 100 * 1024 * 1024,
            "memory_mb": 100.0,
        }

        res = asyncio.run(self.provider.collect())

        self.assertTrue(res["running"])
        self.assertEqual(res["pid"], 1234)
        self.assertEqual(res["cpu_percent"], 2.5)
        self.assertEqual(res["memory_bytes"], 100 * 1024 * 1024)
        mock_test_conn.assert_called_once()

    @patch("app.providers.postgres.check_brew_service")
    @patch("app.providers.postgres.find_process_by_name")
    @patch("app.providers.postgres.is_docker_available")
    @patch("app.providers.postgres.list_containers")
    @patch("app.providers.postgres.get_container_stats")
    @patch("app.providers.postgres._test_connection")
    def test_postgres_docker_mode_skips_host_detection(self, mock_test_conn, mock_stats, mock_list, mock_docker_avail, mock_find_proc, mock_check_brew):
        """Test POSTGRES_MODE=docker SKIPS host detection entirely, even if host process exists."""
        self.settings.POSTGRES_MODE = "docker"
        mock_docker_avail.return_value = DockerStatus(available=True)
        mock_list.return_value = ([
            {
                "ID": "pg_container_123",
                "Name": "hexabeta_postgres_main",
                "State": "running",
                "Status": "Up 2 hours",
            }
        ], None)
        mock_stats.return_value = ({
            "cpu_percent": 3.4,
            "memory_bytes": 250 * 1024 * 1024,
        }, None)

        res = asyncio.run(self.provider.collect())

        # Verify host detection functions were NEVER called
        mock_check_brew.assert_not_called()
        mock_find_proc.assert_not_called()

        self.assertTrue(res["running"])
        self.assertIsNone(res["pid"])  # pid must be None in Docker mode
        self.assertEqual(res["cpu_percent"], 3.4)
        self.assertEqual(res["memory_bytes"], 250 * 1024 * 1024)
        self.assertEqual(res["memory_mb"], 250.0)
        mock_test_conn.assert_called_once()

    @patch("app.providers.postgres.check_brew_service")
    @patch("app.providers.postgres.find_process_by_name")
    @patch("app.providers.postgres.is_docker_available")
    @patch("app.providers.postgres.list_containers")
    @patch("app.providers.postgres.get_container_stats")
    @patch("app.providers.postgres._test_connection")
    def test_postgres_auto_mode_fallback_to_docker(self, mock_test_conn, mock_stats, mock_list, mock_docker_avail, mock_find_proc, mock_check_brew):
        """Test POSTGRES_MODE=auto falls back to Docker when host process is missing."""
        self.settings.POSTGRES_MODE = "auto"
        mock_check_brew.return_value = {"running": False, "pid": None}
        mock_find_proc.return_value = None
        mock_docker_avail.return_value = DockerStatus(available=True)
        mock_list.return_value = ([
            {
                "ID": "pg_container_123",
                "Name": "hexabeta_postgres_main",
                "State": "running",
                "Status": "Up 2 hours",
            }
        ], None)
        mock_stats.return_value = ({
            "cpu_percent": 1.2,
            "memory_bytes": 200 * 1024 * 1024,
        }, None)

        res = asyncio.run(self.provider.collect())

        self.assertTrue(res["running"])
        self.assertIsNone(res["pid"])
        self.assertEqual(res["cpu_percent"], 1.2)
        mock_test_conn.assert_called_once()

    @patch("app.providers.postgres.is_docker_available")
    def test_postgres_missing_docker_gracefully(self, mock_docker_avail):
        """Test missing Docker is handled gracefully in docker mode."""
        self.settings.POSTGRES_MODE = "docker"
        mock_docker_avail.return_value = DockerStatus(available=False, error="Docker CLI not found")

        res = asyncio.run(self.provider.collect())

        self.assertFalse(res["running"])
        self.assertFalse(res["healthy"])
        self.assertIn("Docker not available", res["error"])

    @patch("app.providers.postgres.is_docker_available")
    @patch("app.providers.postgres.list_containers")
    def test_postgres_missing_container_gracefully(self, mock_list, mock_docker_avail):
        """Test no matching container found in docker mode is handled gracefully."""
        self.settings.POSTGRES_MODE = "docker"
        mock_docker_avail.return_value = DockerStatus(available=True)
        mock_list.return_value = ([], None)

        res = asyncio.run(self.provider.collect())

        self.assertFalse(res["running"])
        self.assertFalse(res["healthy"])
        self.assertIn("PostgreSQL service or container not running", res["error"])

    @patch("asyncpg.connect", new_callable=AsyncMock)
    def test_postgres_connection_test_success(self, mock_connect):
        """Test PostgreSQL asyncpg connection test using configured host/port."""
        mock_conn = AsyncMock()
        mock_conn.fetchval.side_effect = ["2026-09-07 10:00:00", "15.4", 5]
        mock_connect.return_value = mock_conn

        res = {"healthy": False, "connection_test": False, "error": None}
        asyncio.run(_test_connection(self.settings, res))

        self.assertTrue(res["connection_test"])
        self.assertTrue(res["healthy"])
        self.assertEqual(res["version"], "15.4")
        self.assertEqual(res["current_connections"], 5)
