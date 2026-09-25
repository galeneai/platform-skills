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

## Browser sign-in through an app backend

Use OpenID Connect Authorization Code with PKCE S256 when the tenant's configured provider supports it. The Galene tenant client is public and has standard flow enabled; the Console demonstrates the PKCE S256 pattern. Do not assume that an app's PKCE or redirect policy is enforced identically in every tenant. Use `GALENE_TENANT_IDP_ISSUER` when the approved capability provides it; otherwise form the expected Keycloak issuer from the public `keycloak.url` and `keycloak.realm` values, then verify it against OIDC discovery. Bind the flow to the app's exact callback and the selected tenant.

Prefer an app backend-for-frontend (BFF) to perform the code exchange server-to-server. Generate and validate `state`, `nonce`, and a PKCE verifier; validate the ID token's signature, expected issuer and client audience, and nonce. The default tenant client allows redirect URIs broadly, but its browser origins include the managed Console origin when one is configured; a wildcard redirect URI does not grant cross-origin browser access to the token endpoint. Do not exchange a code from browser JavaScript on another origin unless that exact origin has been explicitly configured and verified for the tenant.

Keep access and refresh tokens in the BFF's server-side session store. Give the browser an app-owned `Secure`, `HttpOnly`, appropriately `SameSite` session cookie. Protect cookie-authenticated state-changing routes against CSRF. Do not place OIDC tokens in URLs, manifests, app images, local storage, logs, or client-visible app configuration.

Configure the BFF with the explicit public Core API origin for the target. It must be able to reach both the tenant IdP token endpoint and the Core API from the selected Compose and Kubernetes adapters. The manifest's `connectivity` supports component `depends_on`; it has no outbound-host allowlist. Verify runtime network reachability on both adapters, and do not infer that one adapter's egress policy applies to the other.

## Call Core as the signed-in user

The BFF sends the user's access token as `Authorization: Bearer <access token>` only to the configured Galene Core API origin over HTTPS. Core validates the token against the tenant issuer, resolves its user and tenant, and enforces the endpoint's permission and object-level access. The app must separately enforce its own action permissions returned by the app access endpoint. Never forward a caller-supplied token to a URL supplied by that caller or to an external provider; reject redirects on authenticated requests.

For refresh, keep the refresh token server-side and call `POST /public/tenants/{tenant_slug}/auth/refresh` through the BFF; atomically replace the stored token set with the response. On logout, call `POST /public/tenants/{tenant_slug}/auth/logout` with the stored refresh token so the tenant session can be revoked, then delete server-side tokens and clear the app cookie. Handle refresh expiry or revocation by requiring the user to sign in again. Check the target Core `/openapi.json` for the exact operation schemas before implementing these requests.

The publisher's `controlplane_app_publisher` role is for the explicitly selected publisher workflow. It is not an app runtime identity and must not be embedded in an app. Galene provisions no tenant app service account through `identity_provider`.

## Worked flow: tenant document Q&A

Use the following sequence for a tenant app that accepts a user's documents and asks a tenant-bound model. It shows routes and permissions; the app API snapshot in this skill does not include every tenant route's request/response schema.

1. Sign in through the BFF as above. Call `GET /tenant/applications/accessible`, then `GET /tenant/applications/{application_slug}/access`, with the user's bearer token. These routes require an authenticated tenant user and return the user's launch visibility and the app action permissions assigned to that user. Deny the app workflow when access is absent. App action names are not Core endpoint permissions.
2. For a session-scoped upload, the user must have an accessible agent and permission `session.create`. Create a session with `POST /sessions`; Core sets its owner from the authenticated token subject. Do not accept a caller-supplied user ID as the session owner. If the app has no accessible agent/session, use an existing tenant filesystem only when the user has `fs.write` and filesystem access; do not invent an app-owned session.
3. For an app-owned upload, provision the declared filesystem resource with `PUT /tenant/applications/{application_slug}/resources/filesystems/{resource_name}`, then upload the document to `POST /tenant/applications/{application_slug}/resources/filesystems/{resource_name}/sessions/{session_id}/documents`. Both require `application.resource.use`; the session route checks the current user's ownership. The upload queues ingestion. For an existing tenant filesystem, `POST /filesystems/{filesystem_id}/documents` requires `fs.write`, filesystem access, and a writable filesystem. Confirm processing with `GET /rag/files/{attachment_id}/status` (`rag.get`).
4. Search indexed content with `POST /rag/search` (`rag.search`) or the appropriate authorized vector-store search route. Per-user uploaded documents enter ingestion through the selected filesystem; configured knowledge-base connector sync is a separate tenant-admin workflow and keeps source credentials in Core.
5. Ask the model through `POST /v1/chat/completions` (`inference.chat.create`), using the selected tenant model binding and only data the current user can access. A `session_id` may be used for persistence where supported by the target contract. Do not send provider credentials from the app.

Before writing any request body, fetch `/openapi.json` from the exact target Core version and compare the operation, schema, and security requirements with the pinned baseline. If the deployment's commit cannot be established, an operation or schema differs, or an operation is absent, stop and refresh the contract snapshot or choose a documented route for that version. Do not guess payloads. This is especially important for session creation, multipart uploads, RAG search, and model requests.

## Agent/session execution is a separate contract

Use this path when the app backend participates in Galene's agent-driven session execution. It is not an OIDC login flow and the execution assertion is not a tenant API access token.

Declare the manifest's `session_execution` participant as a routable backend component. Its environment schema must declare `ASSISTANT_SESSION_EXECUTION_ASSERTION_KEY` as sensitive and `ASSISTANT_SESSION_EXECUTION_INSTALLATION_ID` as non-secret. Core provisions an installation-specific signing key through a server-side secret reference and the installation ID at runtime. Core-to-app execution callbacks carry a short-lived signed assertion bound to the tenant, installation, session, user, operation, and action. Validate it using the exact committed session-execution contract and fail closed on an invalid, expired, or mismatched assertion.

The session-execution assertion delegates only the signed session operation. It is not a service account, cannot be repurposed as `Authorization: Bearer` for general tenant APIs, and must never be sent to an external service. Core still checks the authenticated tenant user, session binding, permission, and object-level access. If the app must call a tenant API outside this protocol, use the user's separately authenticated BFF session and tenant bearer as described above.
