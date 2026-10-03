"""Same-origin FastAPI integration example; supply the app's protected stores."""
from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol
from urllib.parse import quote, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, SecretStr


class PendingStore(Protocol):
    async def put(self, key: str, value: dict, *, ttl_seconds: int) -> None: ...
    async def take(self, key: str) -> dict | None:
        """Atomically delete and return unexpired state; return None otherwise."""
        ...


EstablishSession = Callable[[Request, Response, dict], Awaitable[None]]
PENDING_COOKIE = "__Host-app_sso"


def https_url(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("Expected a configured HTTPS URL")
    parsed.port
    return value.rstrip("/")


def url_origin(value: str) -> str:
    parsed = urlsplit(value)
    return f"{parsed.scheme}://{parsed.netloc}"


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: SecretStr = Field(min_length=1, max_length=4096)
    totp: str | None = Field(default=None, min_length=4, max_length=12)


class SSOChoice(BaseModel):
    alias: str = Field(min_length=1, max_length=120)


class SSOExchange(BaseModel):
    transaction_id: str = Field(min_length=20, max_length=512)


class PasswordReset(BaseModel):
    identifier: str = Field(min_length=1, max_length=320)


class PasswordResetCompletion(BaseModel):
    reset_token: str = Field(min_length=32, max_length=4096)
    new_password: SecretStr = Field(min_length=1, max_length=4096)
    confirm_new_password: SecretStr = Field(min_length=1, max_length=4096)


class TemporaryPasswordCompletion(BaseModel):
    username: str = Field(min_length=1, max_length=320)
    temporary_password: SecretStr = Field(min_length=1, max_length=4096)
    new_password: SecretStr = Field(min_length=1, max_length=4096)
    confirm_new_password: SecretStr = Field(min_length=1, max_length=4096)
    totp: str | None = Field(default=None, min_length=4, max_length=12)


def make_auth_router(
    *, api_base_url: str, tenant_slug: str, app_origin: str,
    pending: PendingStore, establish_session: EstablishSession,
    client: httpx.AsyncClient,
    login_path: str = "/login", console_fallback_url: str | None = None,
) -> APIRouter:
    """Mount on the app's origin; no caller-provided upstream URLs or tenants.

    Supply a dedicated AsyncClient without default auth, cookies or credentials.
    The caller owns AsyncClient lifespan, rate limiting, protected session
    persistence, refresh/logout and app authorization. Disable request/body
    logging at ingress/APM for auth routes, including the callback query.
    """
    api_base = https_url(api_base_url)
    origin = https_url(app_origin)
    if urlsplit(origin).path:
        raise ValueError("app_origin must be an origin without a path")
    if not tenant_slug:
        raise ValueError("Explicit tenant slug required")
    if urlsplit(origin).port is not None:
        raise ValueError("This facade requires a registered HTTPS login URL without a port")
    if not login_path.startswith("/") or login_path.startswith("//") or any(
        marker in login_path for marker in ("?", "#")
    ):
        raise ValueError("login_path must be an absolute path without query or fragment")
    redirect_uri = origin + login_path
    fallback = https_url(console_fallback_url) if console_fallback_url else None
    base = f"{api_base}/public/tenants/{quote(tenant_slug, safe='')}/auth"
    router = APIRouter(prefix="/auth")

    def same_origin(request: Request) -> None:
        if request.headers.get("origin") != origin:
            raise HTTPException(403, "Invalid request origin")

    async def core(
        method: str,
        path: str,
        body: dict | None = None,
        *,
        error_mode: Literal["generic", "password-reset-complete"] = "generic",
    ) -> dict:
        try:
            # Do not inherit bearer auth, cookies or headers from a user request.
            response = await client.request(
                method, base + path, json=body, follow_redirects=False,
                timeout=20, headers={"Accept": "application/json"},
            )
            data = response.json()
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Tenant sign-in service unavailable") from None
        if not response.is_success:
            challenge = data.get("detail") if isinstance(data, dict) else None
            if (response.status_code == 401 and isinstance(challenge, dict)
                    and challenge.get("challenge") in {"totp_required", "password_update_required"}):
                raise HTTPException(401, {"challenge": challenge["challenge"],
                                          "message": "Additional sign-in step required"})
            status = response.status_code if response.status_code in {400, 401, 403, 409, 422, 429, 503} else 502
            headers = None
            if status == 429 and response.headers.get("Retry-After"):
                headers = {"Retry-After": response.headers["Retry-After"]}
            detail = "Tenant sign-in could not be completed"
            if error_mode == "password-reset-complete":
                if status == 401:
                    detail = "Password reset token is invalid or expired."
                elif status in {409, 422, 429, 503} and isinstance(challenge, str):
                    # These public Core errors are deliberately sanitized and actionable.
                    detail = challenge
            raise HTTPException(status, detail, headers=headers)
        if not isinstance(data, dict):
            raise HTTPException(502, "Unsupported tenant auth response")
        return data

    async def config() -> dict:
        data = await core("GET", "/config")
        password_reset_enabled = data.get("password_reset_enabled", False)
        completion_modes = data.get("password_reset_completion_modes", [])
        if (data.get("tenant_slug") != tenant_slug
                or not isinstance(data.get("credential_login_enabled"), bool)
                or not isinstance(password_reset_enabled, bool)
                or not isinstance(completion_modes, list)
                or any(not isinstance(mode, str) or mode not in {"keycloak", "application"}
                       for mode in completion_modes)
                or not isinstance(data.get("sso_connectors"), list)):
            raise HTTPException(502, "Unsupported tenant auth configuration")
        data = {
            **data,
            "password_reset_enabled": password_reset_enabled,
            "password_reset_completion_modes": completion_modes,
        }
        connectors = data["sso_connectors"]
        if any(not isinstance(item, dict) or not isinstance(item.get("alias"), str)
               or not isinstance(item.get("display_name"), str)
               or not isinstance(item.get("display_order", 0), int)
               for item in connectors):
            raise HTTPException(502, "Unsupported tenant SSO configuration")
        return data

    def enabled_connectors(data: dict) -> list[dict]:
        return sorted(
            (item for item in data["sso_connectors"] if item.get("enabled") is True),
            key=lambda item: item.get("display_order", 0),
        )

    async def finish(request: Request, tokens: dict) -> Response:
        # This response shape must be verified on the selected target.
        if not isinstance(tokens.get("access_token"), str) or not isinstance(tokens.get("user"), dict):
            raise HTTPException(502, "Unsupported tenant token response")
        response = Response(status_code=204, headers={"Cache-Control": "no-store"})
        await establish_session(request, response, tokens)
        response.delete_cookie(PENDING_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return response

    @router.get("/config")
    async def get_config(response: Response):
        data = await config()
        response.headers["Cache-Control"] = "no-store"
        return {
            "credential_login_enabled": data["credential_login_enabled"],
            "password_reset_enabled": data["password_reset_enabled"],
            "password_reset_completion_modes": data["password_reset_completion_modes"],
            "sso_connectors": [
                {"alias": item["alias"], "display_name": item["display_name"]}
                for item in enabled_connectors(data)
            ],
            "recovery": (
                {"mode": "console", "url": fallback}
                if not data["password_reset_enabled"] and fallback
                else None
            ),
        }

    @router.post("/login")
    async def login(payload: Credentials, request: Request):
        same_origin(request)
        if not (await config())["credential_login_enabled"]:
            raise HTTPException(403, "Credential login is disabled")
        tokens = await core("POST", "/login", {
            "username": payload.username,
            "password": payload.password.get_secret_value(),
            **({"totp": payload.totp} if payload.totp else {}),
        })
        return await finish(request, tokens)

    @router.post("/temporary-password")
    async def complete_temporary_password(payload: TemporaryPasswordCompletion, request: Request):
        same_origin(request)
        new_password = payload.new_password.get_secret_value()
        if new_password != payload.confirm_new_password.get_secret_value():
            raise HTTPException(422, "New passwords do not match")
        proof = await core("POST", "/temporary-password/challenge", {
            "username": payload.username,
            "temporary_password": payload.temporary_password.get_secret_value(),
            **({"totp": payload.totp} if payload.totp else {}),
        })
        challenge_token = proof.get("challenge_token")
        expires_in = proof.get("expires_in")
        if (not isinstance(challenge_token, str) or len(challenge_token) < 32
                or not isinstance(expires_in, int) or expires_in < 1):
            raise HTTPException(502, "Unsupported temporary-password challenge response")
        tokens = await core("POST", "/temporary-password/complete", {
            "challenge_token": challenge_token,
            "new_password": new_password,
            **({"totp": payload.totp} if payload.totp else {}),
        })
        return await finish(request, tokens)

    @router.post("/sso/start")
    async def start(payload: SSOChoice, request: Request):
        same_origin(request)
        data = await config()
        if payload.alias not in {item["alias"] for item in enabled_connectors(data)}:
            raise HTTPException(400, "SSO connector is not enabled")
        binding = secrets.token_urlsafe(48)
        started = await core("POST", "/sso/start", {
            "alias": payload.alias, "redirect_uri": redirect_uri,
            "browser_binding": binding,
        })
        authorization_url = started.get("authorization_url")
        keycloak = data.get("keycloak", {})
        if (not isinstance(authorization_url, str)
                or urlsplit(authorization_url).scheme != "https"
                or url_origin(authorization_url) != url_origin(keycloak.get("url", ""))
                or not isinstance(started.get("transaction_id"), str)):
            raise HTTPException(502, "Unsupported SSO start response")
        key = secrets.token_urlsafe(32)
        await pending.put(key, {"binding": binding, "transaction_id": started["transaction_id"]},
                          ttl_seconds=300)
        from fastapi.responses import JSONResponse
        response = JSONResponse({"authorization_url": authorization_url},
                                headers={"Cache-Control": "no-store"})
        response.set_cookie(PENDING_COOKIE, key, max_age=300, path="/",
                            secure=True, httponly=True, samesite="lax")
        return response

    @router.post("/sso/exchange")
    async def exchange(payload: SSOExchange, request: Request):
        same_origin(request)
        key = request.cookies.get(PENDING_COOKIE)
        state = await pending.take(key) if key else None
        if not state or payload.transaction_id.split(".", 1)[0] != state["transaction_id"]:
            raise HTTPException(400, "Invalid, expired or consumed SSO state")
        tokens = await core("POST", "/sso/exchange", {
            "transaction_id": payload.transaction_id, "browser_binding": state["binding"],
        })
        return await finish(request, tokens)

    @router.post("/password-reset", status_code=202)
    async def password_reset(payload: PasswordReset, request: Request):
        same_origin(request)
        auth_config = await config()
        if not auth_config["password_reset_enabled"]:
            raise HTTPException(409, "Password recovery is disabled")
        request_body = {
            "identifier": payload.identifier,
            "redirect_uri": redirect_uri,
        }
        if "application" in auth_config["password_reset_completion_modes"]:
            request_body["completion_mode"] = "application"
        result = await core("POST", "/password-reset", request_body)
        if result.get("accepted") is not True:
            raise HTTPException(502, "Unsupported password recovery response")
        return {"accepted": True}

    @router.post("/password-reset/complete")
    async def complete_password_reset(payload: PasswordResetCompletion, request: Request):
        same_origin(request)
        new_password = payload.new_password.get_secret_value()
        if new_password != payload.confirm_new_password.get_secret_value():
            raise HTTPException(422, "New passwords do not match")
        result = await core(
            "POST",
            "/password-reset/complete",
            {
                "reset_token": payload.reset_token,
                "new_password": new_password,
                "redirect_uri": redirect_uri,
            },
            error_mode="password-reset-complete",
        )
        if result.get("completed") is not True:
            raise HTTPException(502, "Unsupported password recovery response")
        return {"completed": True}

    return router
