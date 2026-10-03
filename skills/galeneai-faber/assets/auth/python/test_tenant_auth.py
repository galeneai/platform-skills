"""Focused BFF wiring checks. Requires the example's fastapi/httpx dependencies."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

SOURCE = Path(__file__).with_name("tenant_auth.py")
spec = importlib.util.spec_from_file_location("faber_auth_example", SOURCE)
auth = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = auth
spec.loader.exec_module(auth)

ORIGIN = "https://notes.example.test"
TX = "00000000-0000-4000-8000-000000000001"
TOKENS = {"access_token": "EXAMPLE-access-not-real", "refresh_token": "sso.EXAMPLE-not-real", "user": {"user_id": "example-user"}}


class FakePending:
    def __init__(self):
        self.values = {}

    async def put(self, key, value, *, ttl_seconds):
        assert ttl_seconds == 300
        self.values[key] = value

    async def take(self, key):
        return self.values.pop(key, None)


class AuthExampleTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.sessions = []
        self.pending = FakePending()
        self.auth_config = {
            "tenant_slug": "acme",
            "credential_login_enabled": True,
            "password_reset_enabled": True,
            "keycloak": {"url": "https://id.example.test"},
            "sso_connectors": [
                {"alias": "second", "display_name": "Second", "enabled": True, "display_order": 20},
                {"alias": "disabled", "display_name": "Disabled", "enabled": False, "display_order": 0},
                {"alias": "first", "display_name": "First", "enabled": True, "display_order": 10},
            ],
        }
        self.login_error = None
        self.client = self.make_client()

    def make_client(self):
        async def upstream(request):
            body = json.loads(request.content) if request.content else None
            self.calls.append((request.url.path, body))
            if request.url.path.endswith("/config"):
                return httpx.Response(200, json=self.auth_config)
            if request.url.path.endswith("/sso/start"):
                return httpx.Response(200, json={
                    "transaction_id": TX,
                    "authorization_url": "https://id.example.test/realms/acme/protocol/openid-connect/auth?state=EXAMPLE",
                })
            if request.url.path.endswith("/password-reset"):
                return httpx.Response(202, json={"accepted": True})
            if request.url.path.endswith("/login") and self.login_error:
                return httpx.Response(401, json=self.login_error)
            return httpx.Response(200, json=TOKENS)

        async def establish(request, response, tokens):
            self.sessions.append(tokens)
            response.set_cookie("__Host-app_sid", "EXAMPLE-opaque-session",
                                secure=True, httponly=True, samesite="lax", path="/")

        app = FastAPI()
        upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
        app.include_router(auth.make_auth_router(
            api_base_url="https://core.example.test", tenant_slug="acme",
            app_origin=ORIGIN, login_path="/login",
            console_fallback_url="https://console.example.test/login",
            pending=self.pending, establish_session=establish,
            client=upstream_client,
        ))
        return TestClient(app, base_url=ORIGIN)

    def post(self, path, body, client=None):
        return (client or self.client).post(path, json=body, headers={"Origin": ORIGIN})

    def test_config_orders_enabled_providers_and_exposes_password_recovery(self):
        response = self.client.get("/auth/config")
        config = response.json()
        self.assertEqual([x["alias"] for x in config["sso_connectors"]], ["first", "second"])
        self.assertTrue(config["password_reset_enabled"])
        self.assertIsNone(config["recovery"])
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_initial_credentials_have_no_totp_and_tokens_stay_server_side(self):
        response = self.post("/auth/login", {"username": "example", "password": "EXAMPLE-not-real"})
        self.assertEqual(response.status_code, 204)
        self.assertNotIn("totp", self.calls[-1][1])
        self.assertEqual(self.sessions, [TOKENS])
        self.assertEqual(response.content, b"")
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertNotIn(TOKENS["access_token"], str(response.headers))

    def test_generic_401_does_not_become_mfa_but_explicit_challenge_does(self):
        self.login_error = {"detail": "invalid credentials"}
        self.assertIsInstance(self.post("/auth/login", {"username": "example", "password": "example"}).json()["detail"], str)
        self.login_error = {"detail": {"challenge": "totp_required", "sensitive_extra": "discard"}}
        response = self.post("/auth/login", {"username": "example", "password": "example"})
        self.assertEqual(response.json()["detail"]["challenge"], "totp_required")
        self.assertNotIn("sensitive_extra", response.text)

    def test_sso_only_disables_credentials(self):
        self.auth_config["credential_login_enabled"] = False
        self.assertEqual(self.client.get("/auth/config").json()["credential_login_enabled"], False)
        self.assertEqual(self.post("/auth/login", {"username": "example", "password": "example"}).status_code, 403)
        self.assertFalse(any(path.endswith("/login") for path, _ in self.calls))

    def test_wrong_origin_has_no_upstream_effect(self):
        response = self.client.post("/auth/sso/start", json={"alias": "first"}, headers={"Origin": "https://other.example.test"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.calls, [])

    def test_sso_binds_browser_and_rejects_replay(self):
        started = self.post("/auth/sso/start", {"alias": "first"})
        self.assertEqual(started.status_code, 200)
        binding = self.calls[-1][1]["browser_binding"]
        self.assertNotIn(binding, started.text)
        self.assertEqual(self.calls[-1][1]["redirect_uri"], ORIGIN + "/login")
        value = TX + ".EXAMPLE-exchange-code-not-real"
        wrong_browser = self.make_client()
        self.assertEqual(self.post("/auth/sso/exchange", {"transaction_id": value}, wrong_browser).status_code, 400)
        self.assertEqual(self.post("/auth/sso/exchange", {"transaction_id": value}).status_code, 204)
        self.assertEqual(self.calls[-1][1]["browser_binding"], binding)
        self.assertEqual(self.sessions, [TOKENS])
        self.assertEqual(self.post("/auth/sso/exchange", {"transaction_id": value}).status_code, 400)

    def test_expired_or_wrong_transaction_cannot_create_session(self):
        self.post("/auth/sso/start", {"alias": "first"})
        self.pending.values.clear()  # Store enforces expiry.
        self.assertEqual(self.post("/auth/sso/exchange", {"transaction_id": TX + ".EXAMPLE-code"}).status_code, 400)
        self.post("/auth/sso/start", {"alias": "first"})
        self.assertEqual(self.post("/auth/sso/exchange", {"transaction_id": "different-transaction.EXAMPLE-code"}).status_code, 400)
        self.assertEqual(self.sessions, [])

    def test_password_reset_uses_registered_login_path_and_neutral_acceptance(self):
        response = self.post("/auth/password-reset", {"identifier": "someone@example.test"})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {"accepted": True})
        self.assertEqual(self.calls[-1], (
            "/public/tenants/acme/auth/password-reset",
            {"identifier": "someone@example.test", "redirect_uri": ORIGIN + "/login"},
        ))

    def test_disabled_password_reset_uses_configured_console_fallback(self):
        self.auth_config["password_reset_enabled"] = False
        config = self.client.get("/auth/config").json()
        self.assertEqual(config["recovery"], {"mode": "console", "url": "https://console.example.test/login"})
        self.calls.clear()
        self.assertEqual(self.post("/auth/password-reset", {"identifier": "someone"}).status_code, 409)
        self.assertFalse(any(path.endswith("/password-reset") for path, _ in self.calls))

    def test_legacy_config_without_reset_flag_uses_console_fallback(self):
        self.auth_config.pop("password_reset_enabled")
        config = self.client.get("/auth/config").json()
        self.assertFalse(config["password_reset_enabled"])
        self.assertEqual(config["recovery"], {"mode": "console", "url": "https://console.example.test/login"})

    def test_tenant_mismatch_does_not_enable_login(self):
        self.auth_config["tenant_slug"] = "other"
        self.assertEqual(self.client.get("/auth/config").status_code, 502)
        self.assertEqual(self.sessions, [])


if __name__ == "__main__":
    unittest.main()
