"""
Unit tests for PostgresProvider (Host mode, Docker mode, missing Docker, connection tests).
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
        self.provider = PostgresProvider()

    @patch("app.providers.postgres.check_brew_service")
    @patch("app.providers.postgres.find_process_by_name")
    @patch("app.providers.postgres.get_process_metrics")
    @patch("app.providers.postgres._test_connection")
    def test_postgres_host_mode(self, mock_test_conn, mock_metrics, mock_find_proc, mock_check_brew):
        """Test PostgreSQL host process detection (macOS mode)."""
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
    def test_postgres_docker_mode(self, mock_test_conn, mock_stats, mock_list, mock_docker_avail, mock_find_proc, mock_check_brew):
        """Test PostgreSQL Docker container detection when host process is missing."""
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
        self.assertIsNone(res["pid"])  # pid should be None in Docker mode
        self.assertEqual(res["cpu_percent"], 1.2)
        self.assertEqual(res["memory_bytes"], 200 * 1024 * 1024)
        self.assertEqual(res["memory_mb"], 200.0)
        mock_test_conn.assert_called_once()

    @patch("app.providers.postgres.check_brew_service")
    @patch("app.providers.postgres.find_process_by_name")
    @patch("app.providers.postgres.is_docker_available")
    def test_postgres_missing_docker_gracefully(self, mock_docker_avail, mock_find_proc, mock_check_brew):
        """Test missing Docker is handled gracefully when host process is also missing."""
        mock_check_brew.return_value = {"running": False, "pid": None}
        mock_find_proc.return_value = None
        mock_docker_avail.return_value = DockerStatus(available=False, error="Docker CLI not found")

        res = asyncio.run(self.provider.collect())

        self.assertFalse(res["running"])
        self.assertFalse(res["healthy"])
        self.assertIn("PostgreSQL service or container not running", res["error"])

    @patch("app.providers.postgres.check_brew_service")
    @patch("app.providers.postgres.find_process_by_name")
    @patch("app.providers.postgres.is_docker_available")
    @patch("app.providers.postgres.list_containers")
    def test_postgres_missing_container_gracefully(self, mock_list, mock_docker_avail, mock_find_proc, mock_check_brew):
        """Test no matching containers found is handled gracefully."""
        mock_check_brew.return_value = {"running": False, "pid": None}
        mock_find_proc.return_value = None
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
