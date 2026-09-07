"""
Unit tests for RedisProvider (Host mode, Docker mode, Auto mode, REDIS_MODE configuration, IP extraction).
"""

import asyncio
from unittest import TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.config import get_settings
from app.providers.redis_provider import RedisProvider, _get_container_ip, _test_redis
from app.utils.docker import DockerStatus


class TestRedisProvider(TestCase):

    def setUp(self):
        self.settings = get_settings()
        self.settings.REDIS_MODE = "auto"
        self.provider = RedisProvider()

    def test_get_container_ip_extraction(self):
        """Test dynamic container IP extraction from docker inspect output."""
        # 1. Direct IPAddress
        inspection_1 = {"NetworkSettings": {"IPAddress": "172.18.0.2"}}
        self.assertEqual(_get_container_ip(inspection_1), "172.18.0.2")

        # 2. Networks dictionary
        inspection_2 = {
            "NetworkSettings": {
                "IPAddress": "",
                "Networks": {
                    "arithwise-hbv1_default": {
                        "IPAddress": "172.18.0.5"
                    }
                }
            }
        }
        self.assertEqual(_get_container_ip(inspection_2), "172.18.0.5")

        # 3. None / Empty
        self.assertIsNone(_get_container_ip(None))
        self.assertIsNone(_get_container_ip({}))

    @patch("app.providers.redis_provider.find_process_by_name")
    @patch("app.providers.redis_provider.get_process_metrics")
    @patch("app.providers.redis_provider._test_redis")
    def test_redis_host_mode(self, mock_test_redis, mock_metrics, mock_find_proc):
        """Test Redis host process detection (host mode)."""
        self.settings.REDIS_MODE = "host"
        mock_proc = MagicMock()
        mock_proc.pid = 5678
        mock_find_proc.return_value = mock_proc
        mock_metrics.return_value = {
            "cpu_percent": 0.5,
            "memory_bytes": 50 * 1024 * 1024,
            "memory_mb": 50.0,
        }

        res = asyncio.run(self.provider.collect())

        self.assertTrue(res["running"])
        self.assertEqual(res["pid"], 5678)
        self.assertEqual(res["cpu_percent"], 0.5)
        self.assertEqual(res["memory_bytes"], 50 * 1024 * 1024)
        mock_test_redis.assert_called_once_with(
            self.settings, res, target_host="127.0.0.1", target_port=6379, is_docker_mode=False
        )

    @patch("app.providers.redis_provider.find_process_by_name")
    @patch("app.providers.redis_provider.is_docker_available")
    @patch("app.providers.redis_provider.list_containers")
    @patch("app.providers.redis_provider.get_container_stats")
    @patch("app.providers.redis_provider.inspect_container")
    @patch("app.providers.redis_provider._test_redis")
    def test_redis_docker_mode_skips_host_detection(self, mock_test_redis, mock_inspect, mock_stats, mock_list, mock_docker_avail, mock_find_proc):
        """Test REDIS_MODE=docker SKIPS host detection entirely and uses dynamic container IP:6379."""
        self.settings.REDIS_MODE = "docker"
        mock_docker_avail.return_value = DockerStatus(available=True)
        mock_list.return_value = ([
            {
                "ID": "redis_container_456",
                "Name": "hexabeta_redis",
                "State": "running",
                "Status": "Up 5 hours",
            }
        ], None)
        mock_stats.return_value = ({
            "cpu_percent": 0.8,
            "memory_bytes": 30 * 1024 * 1024,
        }, None)
        mock_inspect.return_value = ({
            "NetworkSettings": {
                "Networks": {
                    "arithwise-hbv1_default": {
                        "IPAddress": "172.18.0.3"
                    }
                }
            }
        }, None)

        res = asyncio.run(self.provider.collect())

        # Verify host detection functions were NEVER called
        mock_find_proc.assert_not_called()

        self.assertTrue(res["running"])
        self.assertIsNone(res["pid"])  # pid must be None in Docker mode
        self.assertEqual(res["cpu_percent"], 0.8)
        self.assertEqual(res["memory_bytes"], 30 * 1024 * 1024)
        mock_test_redis.assert_called_once_with(
            self.settings, res, target_host="172.18.0.3", target_port=6379, is_docker_mode=True
        )

    @patch("app.providers.redis_provider.find_process_by_name")
    @patch("app.providers.redis_provider.is_docker_available")
    @patch("app.providers.redis_provider.list_containers")
    @patch("app.providers.redis_provider.get_container_stats")
    @patch("app.providers.redis_provider.inspect_container")
    @patch("app.providers.redis_provider._test_redis")
    def test_redis_auto_mode_fallback_to_docker(self, mock_test_redis, mock_inspect, mock_stats, mock_list, mock_docker_avail, mock_find_proc):
        """Test REDIS_MODE=auto falls back to Docker when host process is missing."""
        self.settings.REDIS_MODE = "auto"
        mock_find_proc.return_value = None
        mock_docker_avail.return_value = DockerStatus(available=True)
        mock_list.return_value = ([
            {
                "ID": "redis_container_456",
                "Name": "hexabeta_redis",
                "State": "running",
                "Status": "Up 5 hours",
            }
        ], None)
        mock_stats.return_value = ({
            "cpu_percent": 0.8,
            "memory_bytes": 30 * 1024 * 1024,
        }, None)
        mock_inspect.return_value = ({
            "NetworkSettings": {
                "IPAddress": "172.18.0.7"
            }
        }, None)

        res = asyncio.run(self.provider.collect())

        self.assertTrue(res["running"])
        self.assertIsNone(res["pid"])
        mock_test_redis.assert_called_once_with(
            self.settings, res, target_host="172.18.0.7", target_port=6379, is_docker_mode=True
        )

    @patch("app.providers.redis_provider.is_docker_available")
    def test_redis_missing_docker_gracefully(self, mock_docker_avail):
        """Test missing Docker handles gracefully in docker mode."""
        self.settings.REDIS_MODE = "docker"
        mock_docker_avail.return_value = DockerStatus(available=False, error="Docker CLI not found")

        res = asyncio.run(self.provider.collect())

        self.assertFalse(res["healthy"])
        self.assertIn("Docker not available", res["error"])

    @patch("app.providers.redis_provider.is_docker_available")
    @patch("app.providers.redis_provider.list_containers")
    def test_redis_missing_container_gracefully(self, mock_list, mock_docker_avail):
        """Test missing container handles gracefully in docker mode."""
        self.settings.REDIS_MODE = "docker"
        mock_docker_avail.return_value = DockerStatus(available=True)
        mock_list.return_value = ([], None)

        res = asyncio.run(self.provider.collect())

        self.assertFalse(res["healthy"])
        self.assertIn("Redis service or container not running", res["error"])

    @patch("redis.asyncio.Redis", new_callable=MagicMock)
    def test_redis_connection_test_success(self, mock_redis_cls):
        """Test successful Redis connection test."""
        mock_client = AsyncMock()
        mock_client.ping.return_value = True
        mock_client.info.side_effect = [
            {"redis_version": "7.0.12"},
            {"used_memory": 1048576},
        ]
        mock_redis_cls.return_value = mock_client

        res = {"healthy": False, "ping": False, "error": None, "running": False}
        asyncio.run(_test_redis(self.settings, res, target_host="172.18.0.3", target_port=6379, is_docker_mode=True))

        self.assertTrue(res["ping"])
        self.assertTrue(res["healthy"])
        self.assertEqual(res["version"], "7.0.12")
        self.assertEqual(res["memory_used_bytes"], 1048576)
