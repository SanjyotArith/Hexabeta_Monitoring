"""
Unit tests for app.utils.docker module.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.utils.docker import (
    _parse_percent,
    _parse_size,
    extract_health_from_inspect,
    extract_started_at,
    get_container_stats,
    inspect_container,
    is_docker_available,
    list_containers,
    reset_docker_cache,
)


class TestDockerUtils(unittest.TestCase):
    def setUp(self):
        reset_docker_cache()

    def test_parse_percent(self):
        self.assertEqual(_parse_percent("12.5%"), 12.5)
        self.assertEqual(_parse_percent("0.00%"), 0.0)
        self.assertEqual(_parse_percent("100%"), 100.0)
        self.assertEqual(_parse_percent("invalid"), 0.0)

    def test_parse_size(self):
        self.assertEqual(_parse_size("1024B"), 1024)
        self.assertEqual(_parse_size("1KiB"), 1024)
        self.assertEqual(_parse_size("500MiB"), 500 * 1024 * 1024)
        self.assertEqual(_parse_size("1.5GiB"), int(1.5 * 1024 * 1024 * 1024))
        self.assertEqual(_parse_size("10MB"), 10 * 1000 * 1000)
        self.assertEqual(_parse_size("invalid"), 0)

    def test_extract_health_from_inspect(self):
        inspection = {"State": {"Health": {"Status": "healthy"}}}
        self.assertEqual(extract_health_from_inspect(inspection), "healthy")

        inspection_no_health = {"State": {}}
        self.assertIsNone(extract_health_from_inspect(inspection_no_health))

    def test_extract_started_at(self):
        inspection = {"State": {"StartedAt": "2026-09-07T10:00:00Z"}}
        self.assertEqual(extract_started_at(inspection), "2026-09-07T10:00:00Z")


class TestAsyncDockerUtils(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        reset_docker_cache()

    @patch("app.utils.docker._run_docker_cmd")
    async def test_is_docker_available_success(self, mock_run):
        mock_run.return_value = ("24.0.5", None)
        status = await is_docker_available()
        self.assertTrue(status.available)
        self.assertEqual(status.version, "24.0.5")

    @patch("app.utils.docker._run_docker_cmd")
    async def test_is_docker_available_failure(self, mock_run):
        mock_run.return_value = (None, "Docker CLI not found")
        status = await is_docker_available()
        self.assertFalse(status.available)
        self.assertIn("Docker CLI not found", status.error)

    @patch("app.utils.docker._run_docker_cmd")
    async def test_list_containers_matching(self, mock_run):
        output = (
            '{"ID":"abc123456789","Name":"hexabeta_backend","Image":"img:1","Status":"Up 2 hours","State":"running","Ports":"8000","CreatedAt":"today"}\n'
            '{"ID":"def987654321","Name":"other_service","Image":"img:2","Status":"Up 2 hours","State":"running","Ports":"8001","CreatedAt":"today"}'
        )
        mock_run.return_value = (output, None)

        containers, err = await list_containers(["hexabeta_backend"])
        self.assertIsNone(err)
        self.assertEqual(len(containers), 1)
        self.assertEqual(containers[0]["Name"], "hexabeta_backend")

    @patch("app.utils.docker._run_docker_cmd")
    async def test_get_container_stats(self, mock_run):
        output = '{"CPUPerc":"8.50%","MemUsage":"300MiB / 1GiB","MemPerc":"30.00%"}'
        mock_run.return_value = (output, None)

        stats, err = await get_container_stats("abc123456789")
        self.assertIsNone(err)
        self.assertEqual(stats["cpu_percent"], 8.5)
        self.assertEqual(stats["memory_bytes"], 300 * 1024 * 1024)
        self.assertEqual(stats["memory_limit_bytes"], 1024 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
