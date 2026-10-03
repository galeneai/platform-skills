# Discover the target Core API and OpenAPI

Read this before using a platform endpoint when the user supplies a tenant Console, Control Plane, or installed application URL instead of an API base URL. Discovery is read-only and does not select a tenant or authorize publication.

1. Keep the supplied environment explicit. For a web UI URL, fetch `<scheme>://<host>/galene-config` without credentials. Ignore the input's page path, query and fragment; do not copy sign-in callback values. Use the documented deployment base path if the UI is mounted below a prefix and serves its runtime config there.
2. Read `GALENE_PUBLIC_API_BASE_URL` from that JSON. It is the **Core** API base. `GALENE_PUBLIC_ASSISTANT_API_BASE_URL` or another application BFF URL is not a substitute. A tenant Console also exposes `GALENE_PUBLIC_TENANT_SLUG` / `tenant_slug`; check that it matches the user-selected tenant. A Control Plane URL does not select a tenant.
3. If the user supplies the API base explicitly, use it directly. Fetch `<API_BASE_URL>/openapi.json`, preserving any configured API prefix, without a bearer token. Require a JSON object with an OpenAPI version and `paths`; a successful HTML page, UI OpenAPI, or application BFF schema does not establish the Core contract. Check the relevant public tenant and/or Control Plane operations and their schemas/security.
4. Record the resolved API base, schema URL, retrieval date and target version when exposed, without secrets. Inspect only the operations needed for the task. Keep the downloaded target schema separate from Faber's pinned authoring snapshot; never overwrite the snapshot or its lock with a live response.
5. If runtime config is absent, dynamic, protected, or missing the Core API base, inspect the page's public runtime configuration using the available browser tools or the app's declared non-secret deployment configuration. An arbitrary application is not guaranteed to expose `/galene-config`. If the API still cannot be established, ask for the public Core API base or supported schema URL. Do not guess `api-` hosts, scan hosts/ports, reuse another environment, or send a token to an unverified URL. A blocked OpenAPI endpoint requires a supported public contract from the operator, not private source/DB access.

The helper implements the common root-config and explicit-API cases with HTTPS, timeouts, JSON validation and no redirects:

```sh
python3 scripts/discover_api.py --url https://console.example.invalid/dashboard --output ./target-openapi.json
python3 scripts/discover_api.py --url https://control-plane.example.invalid/applications --output ./target-openapi.json
python3 scripts/discover_api.py --url https://notes.example.invalid/login --output ./target-openapi.json
python3 scripts/discover_api.py --api-base-url https://api.example.invalid --output ./target-openapi.json
```

The three UI examples work only when their runtime config supplies the Core base. The helper prints the resolved base and any public tenant slug, not the full configuration. It accepts no credentials and never follows redirects; for a canonical URL redirect, establish the correct URL and run it again. Keep TLS verification enabled; for a local CA configure the system/Python trust store rather than using an insecure switch.
