"""Same-origin FastAPI integration example; supply the app's protected stores."""
from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from typing import Protocol
from urllib.parse import quote, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field


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
    password: str = Field(min_length=1, max_length=4096)
    totp: str | None = Field(default=None, min_length=4, max_length=12)


class SSOChoice(BaseModel):
    alias: str = Field(min_length=1, max_length=120)


class SSOExchange(BaseModel):
    transaction_id: str = Field(min_length=20, max_length=512)


def make_auth_router(
    *, api_base_url: str, tenant_slug: str, app_origin: str,
    console_recovery_url: str | None, sso_supported: bool,
    pending: PendingStore, establish_session: EstablishSession,
    client: httpx.AsyncClient,
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
    if sso_supported and urlsplit(origin).port is not None:
        raise ValueError("This facade requires a registered HTTPS /login URL without a port")
    recovery = https_url(console_recovery_url) if console_recovery_url else None
    base = f"{api_base}/public/tenants/{quote(tenant_slug, safe='')}/auth"
    router = APIRouter(prefix="/auth")

    def same_origin(request: Request) -> None:
        if request.headers.get("origin") != origin:
            raise HTTPException(403, "Invalid request origin")

    async def core(method: str, path: str, body: dict | None = None) -> dict:
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
            raise HTTPException(status, "Tenant sign-in could not be completed")
        if not isinstance(data, dict):
            raise HTTPException(502, "Unsupported tenant auth response")
        return data

    async def config() -> dict:
        data = await core("GET", "/config")
        if (data.get("tenant_slug") != tenant_slug
                or not isinstance(data.get("credential_login_enabled"), bool)
                or not isinstance(data.get("sso_connectors"), list)):
            raise HTTPException(502, "Unsupported tenant auth configuration")
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
            "sso_connectors": [
                {"alias": item["alias"], "display_name": item["display_name"]}
                for item in enabled_connectors(data)
            ],
            "sso_supported": sso_supported,
            # App adapter config, not an invented Core password-reset field.
            "recovery": {"mode": "console", "url": recovery} if recovery else None,
        }

    @router.post("/login")
    async def login(payload: Credentials, request: Request):
        same_origin(request)
        if not (await config())["credential_login_enabled"]:
            raise HTTPException(403, "Credential login is disabled")
        tokens = await core("POST", "/login", payload.model_dump(exclude_none=True))
        return await finish(request, tokens)

    @router.post("/sso/start")
    async def start(payload: SSOChoice, request: Request):
        same_origin(request)
        if not sso_supported:
            raise HTTPException(409, "App return host is not supported by the tenant SSO contract")
        data = await config()
        if payload.alias not in {item["alias"] for item in enabled_connectors(data)}:
            raise HTTPException(400, "SSO connector is not enabled")
        binding = secrets.token_urlsafe(48)
        started = await core("POST", "/sso/start", {
            "alias": payload.alias, "redirect_uri": origin + "/login",
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
        if not sso_supported:
            raise HTTPException(409, "SSO is unavailable for this app")
        key = request.cookies.get(PENDING_COOKIE)
        state = await pending.take(key) if key else None
        if not state or payload.transaction_id.split(".", 1)[0] != state["transaction_id"]:
            raise HTTPException(400, "Invalid, expired or consumed SSO state")
        tokens = await core("POST", "/sso/exchange", {
            "transaction_id": payload.transaction_id, "browser_binding": state["binding"],
        })
        return await finish(request, tokens)

    return router
