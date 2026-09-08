"""
Unit tests for platform compatibility (macOS vs Linux).
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

from app.utils.service_checker import (
    check_brew_service,
    check_launchctl_service,
    update_cloudflared_launchagent,
)


class TestPlatformCompatibility(unittest.IsolatedAsyncioTestCase):
    @patch("sys.platform", "linux")
    def test_update_cloudflared_launchagent_on_linux(self):
        with patch("pathlib.Path.exists") as mock_exists, patch("pathlib.Path.mkdir") as mock_mkdir:
            update_cloudflared_launchagent()
            # Path.mkdir and Path.exists for /Users should NEVER be called on Linux
            mock_mkdir.assert_not_called()

    @patch("sys.platform", "linux")
    async def test_check_launchctl_service_on_linux(self):
        result = await check_launchctl_service("com.hexa.backend")
        self.assertEqual(result, {"running": False, "pid": None})

    @patch("sys.platform", "linux")
    async def test_check_brew_service_on_linux(self):
        result = await check_brew_service("postgresql@17")
        self.assertEqual(result, {"running": False, "pid": None, "status": "unknown"})


if __name__ == "__main__":
    unittest.main()
