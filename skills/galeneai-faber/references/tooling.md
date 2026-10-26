# Stack-free project tooling

The scripts require Python 3.10+ and use its standard library plus the jsonschema package for standards-compliant JSON Schema validation. Doctor, offline validation, packaging, import-response verification, and their unit tests do not require a running Galene stack. These authoring checks do not prove target-tenant permissions, a live API prerequisite, publication readiness, or runtime readiness. Install the optional Python tool dependency with:

    python3 -m pip install -r scripts/requirements.txt

Resolve a UI URL to the Core API and download the public target OpenAPI with `python3 scripts/discover_api.py --url https://console.example.invalid --output ./target-openapi.json`, or use `--api-base-url` for an explicit Core base. Read [API discovery](api-discovery.md) for missing runtime config, tenant selection and snapshot boundaries. This helper performs unauthenticated read-only requests and needs only the standard library.

`validate.py` also prints non-blocking `WARN:` lines for manifest patterns that fail on real clusters (see [runtime readiness](runtime-readiness.md)); they never change its exit status.

Each project keeps three local files:

- galene-app.json: the public Platform Core application manifest.
- galene-app-project.json: local project context with the selected tenant/environment and registry mode. It contains no credentials and is not included in a release bundle.
- compatibility.json: SemVer, Platform Core commit and contract hashes, registry mode, and per-runtime verification state.

Example:

    python3 scripts/doctor.py --project .
    python3 scripts/validate.py galene-app.json
    python3 scripts/package.py --project . --version 1.2.0 --output dist/team-notes-1.2.0.tar.gz
    python3 scripts/install.py --auth-context publisher --base-url https://control-plane.example --tenant acme-test --app-version 1.2.0 --package-id "$PACKAGE_UUID" --version-id "$VERSION_UUID" --domain-binding web:frontend="$MANAGED_DOMAIN_UUID"

For tenant-scoped install, use --auth-context tenant and a tenant-scoped token instead. The publisher flow reads the selected tenant from the Control Plane catalog and requires controlplane.tenants.read plus controlplane.applications.manage and controlplane.applications.deploy. The tenant flow verifies the exact package/version is available to the authenticated tenant before installation. The user-selected tenant must match galene-app-project.json in either mode. Publisher installation also follows the committed domain-selection contract for that tenant; it does not use infrastructure-domain administration.

Read the bearer token from the approved local secret manager or protected environment as GALENE_CONTROLPLANE_TOKEN or GALENE_TENANT_TOKEN for the chosen context. Do not pass it as a command-line value or copy a token example. The install tool reads only that bearer token, never logs it, and does not accept registry or other secret values.

## Explicit service selections at installation

For nonempty service/resource/model requirements or internal endpoints, `install.py` first fetches the exact target's public `/openapi.json` without a bearer. It qualifies stable Core 1.3+ in major 1 and stable major 2 only when the manifest requirement, installation approval/binding fields and service HTTP routes exist. It checks requested inference operations, model slots/capabilities/modalities and declared context-minimum support; speech also needs the typed application live route. Unknown/development/prerelease identities, future majors and missing shapes stop before authenticated catalog requests or deployment creation. All four declarations empty/absent preserve the legacy flow. The check does not establish native flag enablement, WebSocket protocol support or model readiness; follow [inference interfaces](inference-gateway.md). It neither evaluates arbitrary PEP 440 ranges nor proves tenant prerequisites: Core validates the full `requires_core` range before effects.

After the [application-services snapshot gate](application-services.md#contract-status) is met, install with repeated `--approved-service ROLE` selections and optional `--service-bindings JSON_FILE`. Both tenant and publisher flows accept these fields; the selected tenant must still match project context and the remote catalog. No role is auto-approved from `required`.

```sh
python3 scripts/install.py --auth-context publisher --base-url https://core.example \
  --tenant acme-test --app-version 1.2.0 --package-id "$PACKAGE_UUID" --version-id "$VERSION_UUID" \
  --approved-service files --approved-service cases --service-bindings ./service-bindings.json
```

`service-bindings.json` is a mapping of declared resource roles to **exactly** `{resource_id, access}`:

```json
{
  "workspace": {"resource_id": "00000000-0000-4000-8000-000000000101", "access": "read_write"},
  "case_tools": {"resource_id": "00000000-0000-4000-8000-000000000103", "access": "read"}
}
```

Choose real UUIDs from the authorized target tenant's service-resource catalog. The tool validates manifest role names, unique explicit approvals, UUID/access values, the declared access ceiling, required approvals/resources and bindings for every approved service dependency before HTTP. Only filesystem supports `read_write`. Extra binding fields (including MCP schema hashes or authority), unknown roles and duplicate JSON keys are rejected. Omitted options omit the request fields; supplied selections are sent exactly after validation. Core remains responsible for current tenant ACLs, resource kinds/state and trusted MCP pins. These files contain selections only, never credentials.

`install_deployment` retains its existing optional arguments and adds optional `manifest`, `approved_services`, and `service_bindings`. Pass the authoring manifest whenever selecting services; the helper rejects service selections without it. Legacy calls with none of these arguments retain their request shape. CLI reads the manifest from `galene-app.json`. The transport does not bypass target contract checks or grant installer permission.

Offline validation may use --release to require immutable image digests. Before creating an external-registry package, direct-version release validation must use `--server-url` with `--version`; this calls the validator in the pinned Core snapshot and requires a control-plane token. If the target API returns 404 or its public schema differs from the pinned snapshot, stop the affected operation and give the platform operator a minimal sanitized diagnosis. Use a supported published contract/version; app builders do not refresh the snapshot from an unverified checkout. For integrated archive releases with nonempty service/resource/model requirements or internal endpoints, use `--flow archive-import --release --target-url https://core.example` before any package/import mutation. `--target-url` checks the advertised stable Core version and declared HTTP/model contracts; it is public and needs no token. Native enablement, WebSocket support and readiness need separate verification. The archive-import API validates the full constraint, registry source and inspected images; the direct-version preflight does not accept archive-import manifests. For a stricter/different `requires_core` range, stop before package creation if the available public contract cannot qualify compatibility; obtain a supported preflight from the platform operator rather than inventing an endpoint.

The package script creates a deterministic release bundle containing the canonical manifest, compatibility record, release metadata, and optional release notes. Its compatibility record must match the exact Core commit and schema/OpenAPI hashes in this skill's `snapshot-lock.json`; arbitrary snapshot IDs are rejected. App builders must not change those pins as a workaround for target drift; see [contracts](contracts.md) for maintainer-only snapshot refresh. Integrated manifests may contain multiple `archive_import` components, which must share one internal registry source. App images are separate OCI artifacts; the bundle does not copy source files, images, or archives and does not contain the local tenant/registry project context. Replace `MANAGED_DOMAIN_UUID` in the example with the domain ID the user selected from that tenant's domain-options response.

Authenticated API requests reject HTTP redirects so a bearer token is never forwarded to a different origin. Configure the canonical API origin and path directly.

For each approved vertical slice, run focused app checks that cover the behavior and its concrete risks, then verify required Compose and Kubernetes adapters as scoped by the blueprint. Avoid tests that merely mirror the implementation. The included skill-tool unit tests can be run with:

    python3 -m unittest discover -s tests -v

## Import verification

For an integrated import, save the public import-status response in a protected local file and check it before installation:

    python3 scripts/verify_import.py --manifest galene-app.json --status /protected/import-status.json --expected-images expected-images.json --platform linux/amd64

`expected-images.json` records the intended image reference for each imported component, for example `{"web":"acme/team-notes-web:1.2.0","api":"acme/team-notes-api:1.2.0"}`. Choose the platform for the target, or omit `--platform` if that check is not requested. The tool verifies `ready`, the returned version, complete mappings and digests, and each selected candidate against the intended reference. It supports intentional candidate reuse and does not assume candidate order. It emits only a safe summary, never the full response or staging URLs. This offline check neither authorizes installation nor proves deployment readiness.

The install command calls the selected documented public API, so it needs that API to be reachable and a token from the approved secret manager/environment. It does not require a local platform stack or direct access to platform internals.
