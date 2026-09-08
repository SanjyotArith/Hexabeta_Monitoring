"""
Unit tests for app.providers.backend module.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.providers.backend import BackendProvider, _parse_uptime


class TestBackendProviderHelpers(unittest.TestCase):
    def test_parse_uptime(self):
        started = "2026-09-07T10:00:00.123456789Z"
        uptime = _parse_uptime(started)
        self.assertIsNotNone(uptime)
        self.assertGreater(uptime, 0)

        invalid = "invalid-date"
        self.assertIsNone(_parse_uptime(invalid))

        zero_date = "0001-01-01T00:00:00Z"
        self.assertIsNone(_parse_uptime(zero_date))


class TestBackendProvider(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.provider = BackendProvider()

    @patch("app.providers.backend.get_settings")
    @patch("app.providers.backend._check_health")
    @patch("app.providers.backend.find_hexabeta_processes")
    @patch("app.providers.backend.get_process_metrics")
    async def test_backend_host_mode(
        self, mock_metrics, mock_find, mock_health, mock_settings
    ):
        settings = MagicMock()
        settings.BACKEND_MODE = "host"
        settings.HEXABETA_BACKEND_PORT = 8000
        settings.BACKEND_INTERNAL_HEALTH_URL = "http://localhost:8000/health"
        settings.BACKEND_EXTERNAL_HEALTH_URL = "http://localhost:8000/health"
        mock_settings.return_value = settings

        proc = MagicMock()
        proc.pid = 1234
        proc.create_time.return_value = 100000.0
        mock_find.return_value = [proc]
        mock_metrics.return_value = {"cpu_percent": 5.0, "memory_bytes": 104857600}
        mock_health.return_value = {
            "healthy": True,
            "http_status": 200,
            "response_time_ms": 10.0,
            "version": "1.0.0",
            "error": None,
        }

        result = await self.provider.collect()

        self.assertTrue(result["running"])
        self.assertTrue(result["healthy"])
        self.assertEqual(result["detection_mode"], "host")
        self.assertEqual(result["pid"], 1234)
        self.assertEqual(result["cpu_percent"], 5.0)

    @patch("app.providers.backend.get_settings")
    @patch("app.providers.backend._check_health")
    @patch("app.providers.backend.find_hexabeta_processes")
    @patch("app.utils.docker.is_docker_available")
    @patch("app.utils.docker.list_containers")
    @patch("app.utils.docker.get_container_stats")
    @patch("app.utils.docker.inspect_container")
    async def test_backend_auto_mode_fallback_to_docker(
        self,
        mock_inspect,
        mock_stats,
        mock_list,
        mock_docker_avail,
        mock_find,
        mock_health,
        mock_settings,
    ):
        settings = MagicMock()
        settings.BACKEND_MODE = "auto"
        settings.DOCKER_ENABLED = True
        settings.backend_container_patterns = ["hexabeta_backend"]
        settings.HEXABETA_BACKEND_PORT = 8000
        settings.DOCKER_COMMAND_TIMEOUT = 5
        settings.BACKEND_INTERNAL_HEALTH_URL = "http://localhost:8000/health"
        settings.BACKEND_EXTERNAL_HEALTH_URL = "http://localhost:8000/health"
        mock_settings.return_value = settings

        # Host process not found
        mock_find.return_value = []

        # Docker available and container found
        status_mock = MagicMock()
        status_mock.available = True
        mock_docker_avail.return_value = status_mock

        mock_list.return_value = (
            [
                {
                    "ID": "abc123456789",
                    "Name": "hexabeta_backend",
                    "Image": "backend:latest",
                    "Status": "Up 1 hour",
                    "State": "running",
                    "Ports": "8000->8000",
                    "CreatedAt": "2026-09-08",
                }
            ],
            None,
        )

        mock_stats.return_value = (
            {
                "cpu_percent": 12.0,
                "memory_bytes": 209715200,
                "memory_limit_bytes": 1073741824,
            },
            None,
        )

        mock_inspect.return_value = (
            {
                "State": {
                    "Health": {"Status": "healthy"},
                    "StartedAt": "2026-09-08T00:00:00Z",
                }
            },
            None,
        )

        mock_health.return_value = {
            "healthy": True,
            "http_status": 200,
            "response_time_ms": 15.0,
            "version": "2.1.0",
            "error": None,
        }

        result = await self.provider.collect()

        self.assertTrue(result["running"])
        self.assertTrue(result["healthy"])
        self.assertEqual(result["detection_mode"], "docker")
        self.assertIsNone(result["pid"])
        self.assertEqual(result["cpu_percent"], 12.0)
        self.assertIsNotNone(result["containers"])
        self.assertEqual(len(result["containers"]), 1)
        self.assertEqual(result["containers"][0]["name"], "hexabeta_backend")


if __name__ == "__main__":
    unittest.main()
