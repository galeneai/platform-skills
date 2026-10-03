"""Read-only discovery behavior with public fixture responses."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from discover_api import discover, fetch_json

SPEC = {"openapi": "3.1.0", "paths": {"/public/tenants/{tenant_slug}/auth/config": {}}}


class DiscoveryTests(unittest.TestCase):
    def test_resolves_console_controlplane_and_app_without_callback_query(self):
        for host in ("console.example.test", "control-plane.example.test", "notes.example.test"):
            with self.subTest(host=host), patch("discover_api.fetch_json", side_effect=[
                {"GALENE_PUBLIC_API_BASE_URL": "https://core.example.test/api/",
                 "GALENE_PUBLIC_ASSISTANT_API_BASE_URL": "https://bff.example.test",
                 "GALENE_PUBLIC_TENANT_SLUG": "acme"},
                SPEC,
            ]) as fetch:
                result = discover(ui_url=f"https://{host}/login?sso_transaction=discard#discard")
                self.assertEqual(fetch.call_args_list[0].args, (f"https://{host}/galene-config",))
                self.assertEqual(fetch.call_args_list[1].args, ("https://core.example.test/api/openapi.json",))
                self.assertEqual(result["tenant_slug"], "acme")
                self.assertEqual(result["spec"], SPEC)

    def test_explicit_api_base_needs_no_ui_config_or_tenant_inference(self):
        with patch("discover_api.fetch_json", return_value=SPEC) as fetch:
            result = discover(api_base_url="https://core.example.test/")
        fetch.assert_called_once_with("https://core.example.test/openapi.json")
        self.assertIsNone(result["tenant_slug"])

    def test_missing_config_does_not_guess_host_or_use_app_bff(self):
        with patch("discover_api.fetch_json", return_value={
            "GALENE_PUBLIC_ASSISTANT_API_BASE_URL": "https://bff.example.test",
        }) as fetch:
            with self.assertRaisesRegex(ValueError, "no Core API base"):
                discover(ui_url="https://notes.example.test")
        self.assertEqual(fetch.call_count, 1)

    def test_rejects_credentials_http_and_app_schema(self):
        for source in ("http://core.example.test", "https://user:password@core.example.test"):
            with self.subTest(source=source), patch("discover_api.fetch_json") as fetch:
                with self.assertRaises(ValueError):
                    discover(api_base_url=source)
                fetch.assert_not_called()
        with patch("discover_api.fetch_json", return_value={"openapi": "3.1.0", "paths": {"/auth/login": {}}}):
            with self.assertRaisesRegex(ValueError, "verify Core API"):
                discover(api_base_url="https://bff.example.test")

    def test_public_json_requests_have_no_authorization(self):
        from io import BytesIO
        with patch("discover_api.open_no_redirect", return_value=BytesIO(json.dumps(SPEC).encode())) as opened:
            self.assertEqual(fetch_json("https://core.example.test/openapi.json"), SPEC)
        request = opened.call_args.args[0]
        self.assertIsNone(request.get_header("Authorization"))
        self.assertIsNone(request.get_header("Cookie"))


if __name__ == "__main__":
    unittest.main()
