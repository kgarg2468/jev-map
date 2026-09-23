import io
import json
import os
import subprocess
import sys
import urllib.error
import unittest
from unittest.mock import patch

from jev_map.provider import JevClient, MAX_REQUEST_BYTES, ProviderError
from support import TemporaryRepository


class ProviderTest(TemporaryRepository):
    payload = {"model": "fixture", "state": {}, "questions": {"b0": {"type": "noul"}}}

    def test_real_transport_serialization_with_mocked_network(self):
        response = {"answers": {"b0": {"noul": 0.9}}}
        with patch("urllib.request.build_opener") as factory:
            factory.return_value.open.return_value = io.BytesIO(json.dumps(response).encode())
            actual = JevClient("fixture-secret")(self.payload)
            request = factory.return_value.open.call_args.args[0]
        self.assertEqual(actual, response)
        self.assertEqual(json.loads(request.data), self.payload)
        self.assertEqual(request.get_header("Authorization"), "Bearer fixture-secret")
        self.assertNotIn("fixture-secret", request.data.decode())

    def test_http_errors_do_not_echo_response_or_key(self):
        error = urllib.error.HTTPError("https://example.invalid", 503, "fixture-secret", {}, None)
        with patch("urllib.request.build_opener") as factory:
            factory.return_value.open.side_effect = error
            with self.assertRaisesRegex(ProviderError, "Jev HTTP 503; no automatic retry") as caught:
                JevClient("fixture-secret")(self.payload)
            self.assertEqual(factory.return_value.open.call_count, 1)
        self.assertNotIn("fixture-secret", str(caught.exception))
        self.assertTrue(error.closed)

    def test_malformed_json_and_response_schema(self):
        for body in (b"not json", b"[]", b'{"answers":{"b0":{"noul":true}}}'):
            with self.subTest(body=body):
                with patch("urllib.request.build_opener") as factory:
                    factory.return_value.open.return_value = io.BytesIO(body)
                    with self.assertRaises(ProviderError):
                        JevClient("fixture-secret")(self.payload)

    def test_request_limit_prevents_network_call(self):
        with patch("urllib.request.build_opener") as factory:
            with self.assertRaisesRegex(ProviderError, "request exceeds"):
                JevClient("fixture-secret")({**self.payload, "state": "x" * MAX_REQUEST_BYTES})
            factory.assert_not_called()

    def test_private_env_file_is_parsed_without_shell_evaluation(self):
        self.write(".env.local", "UNRELATED=value\nTYPESAFE_API_KEY='fixture-$(not-a-command)'\n")
        with patch.dict(os.environ, {}, clear=True):
            client = JevClient(env_file=self.root / ".env.local")
        self.assertEqual(client.api_key, "fixture-$(not-a-command)")

    def test_zero_call_refresh_needs_no_key(self):
        self.write("core.py", "class Cleaner:\n    def normalize(self, text):\n        return text.strip()\n")
        self.write("test_core.py", "from core import Cleaner\ndef test_normalize():\n    assert Cleaner().normalize(' a ') == 'a'\n")
        env = {key: value for key, value in os.environ.items() if key != "TYPESAFE_API_KEY"}
        run = subprocess.run([sys.executable, "-m", "jev_map", "--repo", str(self.root),
                              "refresh", "--jev", "--max-calls", "0"], capture_output=True, text=True, env=env)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["enrichment"]["requests"], 0)


if __name__ == "__main__":
    unittest.main()
