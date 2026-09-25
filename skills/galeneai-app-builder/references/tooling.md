# Stack-free project tooling

The scripts use Python's standard library plus the jsonschema package for standards-compliant JSON Schema validation. Doctor, offline validation, packaging, and their unit tests do not require a running Galene stack. Install the optional Python tool dependency with:

    python3 -m pip install -r scripts/requirements.txt

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

Offline validation may use --release to require immutable image digests. Direct external-version release validation should use `--server-url` with `--version`; this calls the validator in the pinned Core snapshot and requires a control-plane token. If a deployment targets an older Core and returns 404, refresh the snapshot and follow that version's documented publication path. For integrated archive releases use `--flow archive-import --release`; the archive-import API validates registry source and inspected images, so do not send that manifest to the direct-version validator.

The package script creates a deterministic release bundle containing the canonical manifest, compatibility record, release metadata, and optional release notes. Its compatibility record must match the exact Core commit and schema/OpenAPI hashes in this skill's `snapshot-lock.json`; arbitrary snapshot IDs are rejected. To target another Core contract, first update and review the skill's pinned snapshots. Integrated manifests may contain multiple `archive_import` components, which must share one internal registry source. App images are separate OCI artifacts; the bundle does not copy source files, images, or archives and does not contain the local tenant/registry project context. Replace `MANAGED_DOMAIN_UUID` in the example with the domain ID the user selected from that tenant's domain-options response.

Authenticated API requests reject HTTP redirects so a bearer token is never forwarded to a different origin. Configure the canonical API origin and path directly.

For test-first development, run the app's own focused unit and contract tests after each vertical slice, then build the component images and verify the same accepted behavior against Compose and Kubernetes adapters as required by the blueprint. The included skill-tool unit tests can be run with:

    python3 -m unittest discover -s tests -v

The install command calls the selected documented public API, so it needs that API to be reachable and a token from the approved secret manager/environment. It does not require a local platform stack or direct access to platform internals.
