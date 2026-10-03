# Next.js and Python tenant sign-in examples

Use these examples when implementing app-owned login. Read [tenant authentication](tenant-authentication.md) and [API discovery](api-discovery.md) first. Copy/adapt the files to the app; they are integration examples, not a new authentication authority or a complete project.

- [Next.js login page](../assets/auth/next/page.tsx): credentials, challenge-driven TOTP, configured SSO choices, SSO return exchange and config-driven password recovery.
- [Python BFF router](../assets/auth/python/tenant_auth.py): public config/credential/SSO/reset calls, server-owned browser binding and return URI, same-origin POST protection, token handoff to the app's existing protected session store and sanitized errors.

Mount the Python router at `/auth`, with the app's reverse proxy serving it on the same origin as Next.js. Copy the page to `app/login/page.tsx`. Use `fastapi` and `httpx` from the app's dependencies. Configure the resolved Core API base, explicit tenant slug, app HTTPS origin and manifest `authentication.login_path` on the server. Configure an operator-confirmed tenant Console `/login` fallback only for targets that lack or disable the public reset contract. Do not let the browser supply an API base, tenant, return URI or recovery URL.

The router deliberately requires two app adapters:

- `PendingStore`: expiring server-side storage with an atomic `take` operation. Store SSO browser binding and transaction ID for at most five minutes, under a random opaque cookie ID. A shared store is required for multiple BFF workers. Keep this material out of logs and browser storage.
- `establish_session(request, response, tokens)`: validate the **target-supported** token/user response and rotate/create the app session in its existing protected store. Retain access/refresh values server-side; set the app's Secure, HttpOnly cookie and expose no tokens in JSON. Apply the app access checks before allowing protected workflows. Implement refresh/revocation/logout as described in tenant authentication. This hook must be implemented before the example is usable; no insecure in-memory session fallback is supplied.

The SSO example uses the public facade:

1. GET tenant auth config; render enabled connectors by `display_order`, using `alias` and `display_name`. Respect `credential_login_enabled`, including SSO-only tenants. LDAP directory connectors are not browser sign-in buttons.
2. BFF generates a browser-bound secret, calls `POST .../auth/sso/start` with `alias`, fixed registered `redirect_uri` and `browser_binding`, and stores the transaction. Redirect the browser to the returned `authorization_url`. Core owns the IdP callback, state, nonce, PKCE and validation for this facade.
3. Core returns to the app's `/login?sso_transaction=<id>.<exchange-code>`. The page removes that value from the visible URL and sends it to the BFF. The BFF atomically consumes the pending transaction for this browser and checks the ID before calling `POST .../auth/sso/exchange` with that complete value and the same binding. Successful exchange creates the app session. Never exchange an IdP code directly in this facade.
4. Treat `refresh_token`, including an opaque `sso.` handle, as opaque. Use the matching public tenant `auth/refresh` and `auth/logout` routes; do not send the handle to Keycloak. The target may omit `expires_in` for SSO.

**Target prerequisite:** publish and install the manifest before SSO or reset. Its optional `authentication.login_path` defaults to `/login` for legacy manifests. Core accepts that exact path only on the active installed frontend domain; it does not accept arbitrary URLs. The example fixes the same registered return URI for SSO and reset and never takes it from the browser.

The BFF exposes the target's `password_reset_enabled` flag and, when enabled, forwards `identifier` plus its fixed registered return URI to Core. It preserves a neutral accepted response and does not create a session or expose tokens. Use the Console fallback only when the flag/contract is unavailable. Do not use temporary-password challenge/complete as forgotten-password recovery.

Run the fixture BFF checks with `python3 -m unittest discover -s skills/galeneai-faber/assets/auth/python -v` from this repository root, using an environment with FastAPI/httpx. Run the discovery/tooling checks with the normal repository suite. Type-check the Next.js page in the app's React/TypeScript environment.

Acceptance: credentials-only initial attempt; generic 401 has no OTP step; documented TOTP challenge does; multiple/disabled/SSO-only connector states; successful SSO plus rejected replay/wrong browser/expired state; reset flag false; reset request uses the fixed installed return and shows neutral accepted confirmation; legacy Console fallback; unavailable config cannot silently enable credentials. Run the app's tests for session rotation, CSRF, tenant and app access. The skill's offline checks verify wiring and examples, not a real IdP login or email delivery.
