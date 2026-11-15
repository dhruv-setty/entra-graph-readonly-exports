import io
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from iato_bau import graph


def _http_error(code, retry_after=None):
    headers = {"Retry-After": retry_after} if retry_after else {}
    return HTTPError("https://graph.microsoft.com/v1.0/users", code, "err", headers, io.BytesIO(b""))


def _response(body):
    response = MagicMock()
    response.read.return_value = body.encode("utf-8")
    response.__enter__.return_value = response
    return response


class GraphClientTests(unittest.TestCase):
    def test_rejects_other_hosts_and_versions(self):
        for url in ("https://attacker.example/v1.0/users", "http://graph.microsoft.com/v1.0/users",
                    "https://graph.microsoft.com/beta/users"):
            with self.assertRaises(ValueError):
                graph.validate_graph_url(url)

    def test_retries_throttling_using_retry_after(self):
        calls = [_http_error(429, "2"), _response('{"value": []}')]
        with patch("iato_bau.graph.urlopen", side_effect=calls), patch("iato_bau.graph.time.sleep") as sleep:
            self.assertEqual(graph.request_json("https://graph.microsoft.com/v1.0/users", "t"), {"value": []})
        sleep.assert_called_once_with(2.0)

    def test_client_errors_are_not_retried(self):
        with patch("iato_bau.graph.urlopen", side_effect=[_http_error(403)]), patch("iato_bau.graph.time.sleep") as sleep:
            with self.assertRaises(HTTPError):
                graph.request_json("https://graph.microsoft.com/v1.0/users", "t")
        sleep.assert_not_called()

    def test_retry_delay_is_capped(self):
        self.assertEqual(graph._retry_delay(0, "600"), graph.MAX_RETRY_DELAY_SECONDS)


if __name__ == "__main__":
    unittest.main()
