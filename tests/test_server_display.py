import unittest

from server import format_cline_endpoint


class ClineEndpointDisplayTests(unittest.TestCase):
    def test_safe_endpoint_is_recommended_when_guard_is_active(self):
        line = format_cline_endpoint("127.0.0.1", 1234, "model-id", True)
        self.assertEqual(
            line,
            "Cline aman (DISARANKAN): http://127.0.0.1:1235/v1 | Model ID: model-id",
        )

    def test_unprotected_endpoint_is_labeled_clearly(self):
        line = format_cline_endpoint("127.0.0.1", 1234, "model-id", False)
        self.assertEqual(
            line,
            "Cline tanpa pengaman: http://127.0.0.1:1234/v1 | Model ID: model-id",
        )

    def test_safe_port_follows_custom_api_port(self):
        line = format_cline_endpoint("0.0.0.0", 8000, "model-id", True)
        self.assertIn("http://127.0.0.1:8001/v1", line)


if __name__ == "__main__":
    unittest.main()
