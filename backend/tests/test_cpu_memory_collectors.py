"""
Unit tests for CpuCollector and MemoryCollector (host mode vs Docker fallback).
"""

import unittest
from unittest.mock import MagicMock, patch

from app.collectors.cpu import CpuCollector
from app.collectors.memory import MemoryCollector
from app.utils.docker import DockerStatus


class TestCpuMemoryCollectors(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cpu_collector = CpuCollector()
        self.memory_collector = MemoryCollector()

    @patch("app.collectors.cpu.get_settings")
    @patch("app.collectors.cpu.find_hexabeta_processes")
    async def test_cpu_collector_host_processes(self, mock_find, mock_settings):
        settings = MagicMock()
        settings.DOCKER_ENABLED = True
        mock_settings.return_value = settings

        proc = MagicMock()
        proc.cpu_percent.return_value = 15.5
        mock_find.return_value = [proc]

        res = await self.cpu_collector.collect()
        self.assertEqual(res, {"cpu_percent": 15.5})

    @patch("app.collectors.cpu.get_settings")
    @patch("app.collectors.cpu.find_hexabeta_processes")
    @patch("app.collectors.cpu.is_docker_available")
    @patch("app.collectors.cpu.list_containers")
    @patch("app.collectors.cpu.get_container_stats")
    async def test_cpu_collector_docker_fallback(
        self, mock_stats, mock_list, mock_docker_avail, mock_find, mock_settings
    ):
        settings = MagicMock()
        settings.DOCKER_ENABLED = True
        settings.backend_container_patterns = ["hexabeta_backend"]
        settings.DOCKER_COMMAND_TIMEOUT = 5
        mock_settings.return_value = settings

        mock_find.return_value = []
        mock_docker_avail.return_value = DockerStatus(available=True)
        mock_list.return_value = ([{"ID": "c123"}], None)
        mock_stats.return_value = ({"cpu_percent": 8.4}, None)

        res = await self.cpu_collector.collect()
        self.assertEqual(res, {"cpu_percent": 8.4})

    @patch("app.collectors.memory.get_settings")
    @patch("app.collectors.memory.find_hexabeta_processes")
    async def test_memory_collector_host_processes(self, mock_find, mock_settings):
        settings = MagicMock()
        settings.DOCKER_ENABLED = True
        mock_settings.return_value = settings

        proc = MagicMock()
        mem_info = MagicMock()
        mem_info.rss = 104857600
        proc.memory_info.return_value = mem_info
        mock_find.return_value = [proc]

        res = await self.memory_collector.collect()
        self.assertEqual(res["memory_bytes"], 104857600)
        self.assertEqual(res["memory_mb"], 100.0)

    @patch("app.collectors.memory.get_settings")
    @patch("app.collectors.memory.find_hexabeta_processes")
    @patch("app.collectors.memory.is_docker_available")
    @patch("app.collectors.memory.list_containers")
    @patch("app.collectors.memory.get_container_stats")
    async def test_memory_collector_docker_fallback(
        self, mock_stats, mock_list, mock_docker_avail, mock_find, mock_settings
    ):
        settings = MagicMock()
        settings.DOCKER_ENABLED = True
        settings.backend_container_patterns = ["hexabeta_backend"]
        settings.DOCKER_COMMAND_TIMEOUT = 5
        mock_settings.return_value = settings

        mock_find.return_value = []
        mock_docker_avail.return_value = DockerStatus(available=True)
        mock_list.return_value = ([{"ID": "c123"}], None)
        mock_stats.return_value = ({"memory_bytes": 209715200}, None)

        res = await self.memory_collector.collect()
        self.assertEqual(res["memory_bytes"], 209715200)
        self.assertEqual(res["memory_mb"], 200.0)


if __name__ == "__main__":
    unittest.main()
