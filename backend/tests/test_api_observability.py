"""
Unit tests for ApiObservabilityReader missing DB fallback behavior.
"""

import unittest
from unittest.mock import patch

from app.core.api_observability import ApiObservabilityReader


class TestApiObservability(unittest.TestCase):
    @patch("pathlib.Path.exists")
    def test_missing_database_returns_empty_metrics_cleanly(self, mock_exists):
        """Verify that a missing api_observability.db returns clean zeroed metrics without crashing."""
        mock_exists.return_value = False

        reader = ApiObservabilityReader()
        metrics = reader.get_metrics()

        self.assertIsNotNone(metrics)
        self.assertIn("summary", metrics)
        self.assertIn("endpoints", metrics)

        summary = metrics["summary"]
        self.assertEqual(summary["total_requests"], 0)
        self.assertEqual(summary["requests_per_second"], 0.0)
        self.assertEqual(metrics["endpoints"], [])
        self.assertEqual(metrics["slow_endpoints"], [])
        self.assertEqual(metrics["exceptions"], [])


if __name__ == "__main__":
    unittest.main()
