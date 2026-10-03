# Tenant user authentication and Core API access

Read this guide when an app handles individual tenant users or calls Core tenant APIs. The tenant access token represents the signed-in user. It is not a Control Plane publisher token, an app service account, or a platform secret.

## Public tenant identity metadata

Before sign-in, call the unauthenticated, frontend-safe `GET /public/tenants/{tenant_slug}/auth/config`. It returns the active tenant's public Keycloak realm/client information and enabled public SSO hints; it does not return client secrets. The essential shape is:

```json
{
  "tenant_slug": "acme-test",
  "display_name": "Acme Test",
  "keycloak": {
    "url": "https://id.example.invalid",
    "realm": "acme-test",
    "client_id": "galene-tenant"
  },
  "credential_login_enabled": true,
  "sso_connectors": []
}
```

The `identity_provider` capability, when declared and approved, provisions these non-secret runtime values for the selected app components:

- `GALENE_TENANT_IDP_ISSUER`
- `GALENE_TENANT_IDP_CLIENT_ID`
- `GALENE_TENANT_AUTH_CONFIG_URL`

The public client ID is normally `galene-tenant`. These values identify the tenant identity provider; they do not authenticate a workload, mint a token, or grant any Core permission. `core_api` declares that the app needs Core API access; it also provides no credential or RBAC bypass.

## Login options, SSO and password recovery

Fetch the active tenant auth config before rendering the login options; on failure show a recoverable error rather than silently enabling credentials. When the target supports returns for the selected app, show every enabled browser SSO connector in `display_order`, with its `display_name` and `alias`. Keep supported SSO choices visible alongside the username/password form, and hide the credential form when `credential_login_enabled` is false. Do not turn LDAP directory entries into browser SSO buttons or hardcode provider names.

The pinned public SSO facade exposes `POST /public/tenants/{tenant_slug}/auth/sso/start` and `.../exchange`, with browser/tenant binding and Core-owned state/nonce/PKCE. Its return registration is currently limited to the active installed **Assistant** frontend at `/login`; a generic tenant app cannot register its return through this manifest baseline. `authentication.login_path` is absent from the pinned schema. Do not add that field, rename the app to Assistant, borrow its domain or infer generic SSO support from connector discovery. A new app requiring SSO must stop that slice and obtain a supported public return contract from the platform operator. For a separately verified target supporting generic app returns, bind the exact registered HTTPS host/path; reject query strings, fragments, ports and caller-selected returns.

### Password recovery requires a separate target contract

The Core baseline selected for this release does not expose public password-reset routes or `password_reset_enabled` / `password_reset_completion_modes` in its auth config. Keep app reset unavailable on that baseline; use an operator-confirmed tenant Console recovery destination only when that destination supplies the needed flow. Do not infer recovery from SMTP, credential login, temporary-password endpoints or Keycloak metadata.

The following reset flow and the optional reset branches in the auth templates apply **only** to another target whose verified public OpenAPI documents both reset routes and whose public config advertises recovery. They are outside this release's pinned Core contract. A missing route is a prerequisite to resolve with the platform operator, not permission to implement or call a guessed API.

For such a verified target, read `password_reset_enabled` and `password_reset_completion_modes` from the public config. When reset is enabled and `application` is advertised, include “Forgot password?” and have the BFF call `POST /public/tenants/{tenant_slug}/auth/password-reset` with `{"identifier":"…","redirect_uri":"https://<installed-app-host><login_path>","completion_mode":"application"}`. The BFF fixes the return URI from trusted server configuration; it never accepts an arbitrary browser-selected target. A successful request returns HTTP 202 with `{"accepted":true}` for known, unknown and non-resettable accounts, so show the same neutral confirmation in every accepted case. Handle HTTP 422 as invalid registration/input, 409 as disabled realm policy, 429 with its `Retry-After`, and 503 as a temporary identity, SMTP or limiter failure without revealing account existence.

Application completion emails return to the exact registered login path with `#password_reset_token=<opaque>`. On first script execution, remove the fragment with `history.replaceState` before making network requests or rendering it anywhere. Keep the token only in page memory and submit it with the confirmed new password to the same-origin BFF. The BFF calls `POST /public/tenants/{tenant_slug}/auth/password-reset/complete` with `{"reset_token":"…","new_password":"…","redirect_uri":"https://<installed-app-host><login_path>"}`. HTTP 200 returns `{"completed":true}` and creates no session; require normal sign-in afterward. Do not persist the token or password in browser storage, cookies, logs, telemetry, URLs, exception text or app data. The app never needs Keycloak administrator credentials.

The reset proof expires after 15 minutes and is bound to its tenant, installed application and registered return URI. HTTP 401 means the token is invalid, expired, consumed, or belongs to another tenant/app; discard it and request a new email. A password-policy HTTP 422 happens before the password write and preserves the proof for another password attempt without extending its expiry. A 422 registration/return mismatch means the link cannot be used by this app. Treat an ambiguous failure after consumption as terminal and request a new email. Handle 409 as reset disabled, 429 according to `Retry-After`, and 503 as temporary unavailability. A callback already received may still show its completion form when a later config read says reset is disabled, because the completion operation does not depend on sending another email.

When reset is enabled but `application` is not advertised, omit `completion_mode`; Core's default `keycloak` behavior hosts the completion action and returns the browser to the registered login path. Targets predating completion modes omit `password_reset_completion_modes`, so omitting the new request field preserves compatibility. An explicit empty modes list means no advertised completion mode. When `password_reset_enabled` is false, use an operator-confirmed tenant Console `/login` fallback only if that destination provides the needed recovery flow. Do not infer reset availability from SMTP, credential login or Keycloak metadata. Temporary-password update is a separate first-login challenge and must never be called for forgotten-password recovery.

Read [the Next.js/Python examples](auth-examples.md) for the config-driven login page, facade callback and protected BFF handoff. Use [API discovery](api-discovery.md) when the only supplied address is a UI URL.

## App login through the BFF and public Galene API

For ordinary tenant credential sign-in, keep the username/password form on the app's own origin. The browser submits to the app's BFF over HTTPS; the BFF calls Galene's public `POST /public/tenants/{tenant_slug}/auth/login` endpoint over HTTPS with the required username and password. Do not show an OTP field in the initial form or send a TOTP proactively. Add and submit a TOTP only after the response explicitly signals that this user must complete an MFA challenge, using the exact challenge shape verified against the selected target's public contract. A generic 401, invalid-credentials response, or tenant auth configuration value is not an MFA challenge: tenant MFA policies may have user exemptions. The known `401` challenge value `detail.challenge: "totp_required"` is a challenge signal only where the selected target's public contract documents that response shape. The public request accepts optional/null `totp`, constrained to 4–12 characters when supplied; this is still the tenant auth route, not `/console/auth/login`.

Treat the login response according to the actual public response contract for the selected target. For public sign-in operations included in the bundled snapshot, compare the target's token/user schema with the pinned version; do not invent an envelope or fields. The app's BFF should consume only the supported response shape and expose only the app session to the browser. Galene remains the identity authority: do not build app-local identities, validate credentials independently, or create an app service account.

Credential and TOTP values are transient inputs. Never persist them, put them in URLs or command arguments, or write them to logs, telemetry, screenshots, or error messages. Store the resulting access/refresh token set only in the BFF's protected server-side session store, encrypted at rest where persisted. Give the browser an app-owned `Secure`, `HttpOnly`, appropriately `SameSite` session cookie. Protect cookie-authenticated writes with CSRF validation and same-origin/Origin checks. Do not expose bearer or refresh tokens in browser storage or client-visible configuration.

## Temporary passwords and first sign-in

An ordinary `POST /public/tenants/{tenant_slug}/auth/login` may return HTTP 401 with `detail.challenge: "password_update_required"`. Only that typed response starts first sign-in; an ordinary 401 does not. Keep the submitted username and temporary password in page memory while the user enters and confirms a new password. Do not turn this into an app-local account or send the user to a tenant-admin flow.

The BFF first calls `POST /public/tenants/{tenant_slug}/auth/temporary-password/challenge` with `{"username":"…","temporary_password":"…"}`. Add `totp` only if that operation explicitly returns HTTP 401 with `detail.challenge: "totp_required"`; the public tenant sign-in flow is distinct from the Console MFA flow. Success returns a single-use `challenge_token` with `expires_in` (300 seconds by default). Keep that Core token inside the BFF request and immediately call `POST /public/tenants/{tenant_slug}/auth/temporary-password/complete` with the token, confirmed new password, and the same TOTP when one was requested. The completion response is the normal `AuthTokenResponse`; pass it to the app's existing protected session-store adapter and expose only the app session cookie to the browser.

The completion consumes its challenge before changing the password. A password-policy rejection requires starting again with a fresh challenge; do not replay the consumed token. If a later sign-in step fails after the write, Core returns a typed detail with `password_updated: true`, preserving the original HTTP status. The BFF passes a sanitized `totp_required` challenge only when Core explicitly returned it and normalizes every other marked required action to `sign_in_required`. Replace the temporary credential held in page memory with the new password and return to ordinary login; request a fresh TOTP only for the explicit TOTP challenge. Never retry temporary-password completion after this marker. Keep all credential proof, new passwords, TOTP values and challenge tokens in memory only and out of logs. Core owns the account and credential update; the app BFF never receives or embeds administrator credentials.

Read `credential_login_enabled` from the public tenant auth config. If it is false, respect the tenant's enabled SSO flow. Do not force-enable credentials, silently redirect to Keycloak, or fall back to direct IdP token exchange. If the selected tenant requires SSO but no supported public sign-in flow is available to the app, stop and give the platform operator a minimal sanitized diagnosis.

An external tenant SSO provider requires a redirect as part of the app's selected, supported SSO sign-in workflow; choosing a configured provider from the login page does not require a separate approval. Start sign-in from the app and do not use Keycloak's login page as a fallback. If the target supports a direct OIDC Authorization Code adapter instead of the public facade, bind state, nonce, PKCE verifier, callback, and tenant; validate issuer, audience, nonce, and signature server-side. Those OIDC checks belong to the code flow; credential login still needs its own CSRF protection. Do not exchange an IdP code in browser JavaScript on an unapproved origin. For first-login MFA or another required user action, use only the target's documented public contract; if it cannot be completed through that contract, stop with a minimal sanitized diagnosis and refer it to the platform operator. Never infer a challenge from a generic authentication failure, fall back to an undocumented/private API, or weaken/skip the required challenge.

Configure the BFF with the explicit public Core API origin. The normal credential flow requires the app runtime to reach that API; direct IdP reachability is needed only for a specifically approved documented SSO flow. Verify the required network path for each selected adapter. The manifest's `connectivity` supports component `depends_on`; it has no outbound-host allowlist.

For refresh, keep the refresh token server-side and call `POST /public/tenants/{tenant_slug}/auth/refresh` through the BFF; atomically replace the stored token set with the supported response. On logout, call `POST /public/tenants/{tenant_slug}/auth/logout` with the stored refresh token so the tenant session can be revoked, then delete server-side tokens and clear the app cookie. Handle refresh expiry or revocation by requiring the user to sign in again. A future JWT expiry does not prove that the IdP session remains valid. For long jobs, retain the initiating identity and require reauthentication plus a deliberate retry if authorization expires. Never silently substitute another user's identity.

## Call Core as the signed-in user

The BFF sends the user's access token as `Authorization: Bearer <access token>` only to the configured Galene Core API origin over HTTPS. Core validates the token against the tenant issuer, resolves its user and tenant, and enforces the endpoint's permission and object-level access. The app must separately enforce its own action permissions returned by the app access endpoint. Never forward a caller-supplied token to a URL supplied by that caller or to an external provider; reject redirects on authenticated requests.

The publisher's `controlplane_app_publisher` role is for the explicitly selected publisher workflow. It is not an app runtime identity and must not be embedded in an app. Galene provisions no tenant app service account through `identity_provider`.

## Worked flow: tenant document Q&A

Use the following sequence for a tenant app that accepts a user's documents and asks a tenant-bound model. It shows routes and permissions; the app API snapshot in this skill does not include every tenant route's request/response schema.

1. Sign in through the BFF as above. Call `GET /tenant/applications/accessible`, then `GET /tenant/applications/{application_slug}/access`, with the user's bearer token. These routes require an authenticated tenant user and return the user's launch visibility and the app action permissions assigned to that user. Deny the app workflow when access is absent. App action names are not Core endpoint permissions.
2. For a session-scoped upload, the user must have an accessible agent and permission `session.create`. Create a session with `POST /sessions`; Core sets its owner from the authenticated token subject. Do not accept a caller-supplied user ID as the session owner. If the app has no accessible agent/session, use an existing tenant filesystem only when the user has `fs.write` and filesystem access; do not invent an app-owned session.
3. For an app-owned upload, provision the declared filesystem resource with `PUT /tenant/applications/{application_slug}/resources/filesystems/{resource_name}`, then upload the document to `POST /tenant/applications/{application_slug}/resources/filesystems/{resource_name}/sessions/{session_id}/documents`. Both require `application.resource.use`; the session route checks the current user's ownership. The upload queues ingestion. For an existing tenant filesystem, `POST /filesystems/{filesystem_id}/documents` requires `fs.write`, filesystem access, and a writable filesystem. Confirm processing with `GET /rag/files/{attachment_id}/status` (`rag.get`).
4. Search indexed content with `POST /rag/search` (`rag.search`) or the appropriate authorized vector-store search route. Per-user uploaded documents enter ingestion through the selected filesystem; configured knowledge-base connector sync is a separate tenant-admin workflow and keeps source credentials in Core.
5. Ask the model through `POST /v1/chat/completions` (`inference.chat.create`), using the selected tenant model binding and only data the current user can access. A `session_id` may be used for persistence where supported by the target contract. Do not send provider credentials from the app.

Before writing a request body, inspect the target's public `/openapi.json` for that operation, schema, and security requirements. Use the published skill snapshot for the routes it covers; it does not replace the tenant operation schemas. If a required operation is absent, incompatible, or its supported contract cannot be established, stop that slice and request the supported public contract/version from the platform operator. Do not guess payloads, change pinned hashes, or assume access to Core source. This is especially important for session creation, multipart uploads, RAG search, and model requests.

## Agent/session execution is a separate contract

Use this path when the app backend participates in Galene's agent-driven session execution. It is not an OIDC login flow and the execution assertion is not a tenant API access token.

Declare the manifest's `session_execution` participant as a routable backend component. Its environment schema must declare `ASSISTANT_SESSION_EXECUTION_ASSERTION_KEY` as sensitive and `ASSISTANT_SESSION_EXECUTION_INSTALLATION_ID` as non-secret. Core provisions an installation-specific signing key through a server-side secret reference and the installation ID at runtime. Core-to-app execution callbacks carry a short-lived signed assertion bound to the tenant, installation, session, user, operation, and action. Validate it using the exact committed session-execution contract and fail closed on an invalid, expired, or mismatched assertion.

The session-execution assertion delegates only the signed session operation. It is not a service account, cannot be repurposed as `Authorization: Bearer` for general tenant APIs, and must never be sent to an external service. Core still checks the authenticated tenant user, session binding, permission, and object-level access. If the app must call a tenant API outside this protocol, use the user's separately authenticated BFF session and tenant bearer as described above.
