# Publish, make available, and install

Follow this sequence after the user approves the blueprint and explicitly chooses a tenant and image registry. Read the contract snapshot in [contracts](contracts.md) before calling these routes. The local scripts prepare and verify artifacts; they do not create a catalog version or mark it available.

## Prepare the release

1. Set the immutable SemVer, target tenant/environment, registry mode, required Platform Core version range, and contract hashes in the project compatibility matrix.
2. Build each app component with behavior that has passed its app tests. Verify the app against both Compose and Kubernetes adapters when both are in scope.
3. For an owner-managed external OCI registry, push every component image and record its sha256 digest. Use manifest image_source entries that name the verified RegistrySource ID, repository, and immutable digest. Prefer an existing verified source. If a source must be created or verified, use a publisher with `controlplane.registry_sources.manage` or another authorized registry-source manager. The pinned `controlplane_app_publisher` role includes that permission. An external RegistrySource needs an HTTPS registry origin and an explicitly supplied username/password pair entered through the secure registry-source flow. Never place credentials in project files, arguments, release archives, or examples.
4. For the integrated registry, follow [the concrete multi-image archive build and candidate mapping flow](integrated-registry.md#build-and-select-multiple-images) for all components assigned to archive_import. All archive_import components in one release use the same enabled, verified internal RegistrySource. Obtain its ID through an authorized source manager if it is not already known. The server importer checks this source; offline schema validation cannot prove it is internal or verified.
5. Run doctor and validate. Direct-version publication must also use the pinned server validator; integrated archive imports are validated by the archive-import API. Run package.py to create the deterministic manifest/compatibility/release-metadata bundle. The bundle does not contain app source, component images, image archives, secrets, or galene-app-project.json.

## Publish an external-registry version

Use the documented Control Plane application endpoints with a publisher authorized for the target tenant:

1. Find the package in GET /controlplane/applications. If it does not exist, create it with POST /controlplane/applications using the app slug and name.
2. Validate the exact new-version request with POST /controlplane/application-manifests/validate and body {package_slug, version, manifest}. A valid request returns 200 {valid: true, errors: []}; invalid input returns 422 {valid: false, errors: [{path, message, type}]}. The response does not echo the manifest or input context. This check has controlplane.applications.manage permission and no write side effects.
3. Create the immutable version with POST /controlplane/applications/{package_id}/versions using {version, manifest, status?, release_notes?}. Core repeats publication validation; the schema and local validator do not replace it.
4. Select the target tenant explicitly from GET /controlplane/tenants (`controlplane.tenants.read`) and retain its tenant ID.
5. Make the version available to that tenant with POST /controlplane/applications/{package_id}/availability using {tenant_id, version_id, status: "available"}. Verify the availability record before installation.

Do not send archive_import through the direct new-version endpoint. The version validator rejects archive_import because integrated publication has a separate importer.

## Publish through the integrated registry

Use the committed multi-component archive-import contract only when its routes are in the pinned Core snapshot:

1. Find the app package with GET /controlplane/applications or create it with POST /controlplane/applications using the manifest slug and app name. Keep its package ID.
2. Select the target tenant explicitly from GET /controlplane/tenants (`controlplane.tenants.read`) and keep its tenant ID.
3. Create one archive-import operation at POST /controlplane/applications/{package_id}/archive-imports. Its JSON metadata includes tenant_id, version, manifest, archive_filename, and optional release_notes; upload the image archive using the documented multipart flow. Use [the inspected-candidate mapping instructions](integrated-registry.md#build-and-select-multiple-images) to select the image for every imported component.
4. After inspection, read candidate_images and component_names. If there is one imported component and one candidate, Core may auto-select it. Otherwise call POST /controlplane/application-archive-imports/{import_id}/select-images with mappings that cover every imported component exactly once. A candidate may be reused for multiple components when that is the approved mapping.
5. Let Core copy each selected image to its target repository and record each sha256 digest. The version and tenant availability are published together only after all copies succeed. Retry/cancel operations preserve successful digests; failed or cancelled partial copies do not create a catalog version or availability.
6. Check the operation's final version and availability before installation. Verify the saved final import response and intended full image references with [the offline import verifier](tooling.md#import-verification) before proceeding; it checks the mapping and digests but does not authorize the API operation or prove runtime readiness.

Integrated archive imports use one verified internal RegistrySource for every archive_import component in the release. Do not make separate imports and describe them as one atomic release. If the final import API is not in the selected Core snapshot, publish a single component through its available integrated flow, use a verified external OCI source for a multi-component app, or defer publication.

## Install to the selected tenant

For the publisher path, install.py resolves the explicit tenant slug against GET /controlplane/tenants and verifies the selected package/version IDs. Its publisher role requires controlplane.tenants.read, controlplane.applications.manage, and controlplane.applications.deploy. The documented publisher endpoints create the tenant deployment; this is the delegated cross-tenant workflow.

For each manifest route with host_required true, first read GET /controlplane/tenants/{tenant_id}/application-domain-options. Select a managed_domain_id from that tenant's returned {id, host, display_name} options and pass one --domain-binding COMPONENT:ROLE=MANAGED_DOMAIN_ID to install.py per route. The publisher does not need infrastructure-domain read/manage permission or a Register Domain operation. Core binds each domain with POST /controlplane/application-deployments/{deployment_id}/domains using component_name, route_role, and managed_domain_id. Routes with host_required false need no binding.

The install script checks all required route selections against the tenant's options before creating the deployment. If domain binding fails after deployment creation, it reports the deployment ID and the incomplete route so the user can finish through the documented Control Plane UI/API. Never report an accepted or pending install as ready. Verify deployment status, the selected route, and the approved first workflow in the target tenant.

If the user chooses tenant-scoped installation, use the documented tenant app catalog/deployment APIs and permissions with a tenant token. Use the tenant UI for any required domain selection that the tenant API contract does not expose to the selected role. Keep the same explicit tenant and readiness checks.

## Service approvals and resource bindings

For the [application-services extension](application-services.md), first meet its committed-snapshot gate. During installation/upgrade, approve required service roles and bind declared tenant resource roles using the supported Console/Control Plane controls or verified deployment API. Model selection stays separate. The current `install.py` has no service approval/binding inputs, so use the verified UI/API for service-dependent apps until tooling is upgraded; it cannot infer these choices. Preserve omitted PATCH fields on unrelated edits. Settings can revoke service approval without deleting the deployment; the app must handle denied access. Verify one affected workflow and the directly relevant denial/revocation case after review on the assigned beta environment. Kubernetes verification, backup/support and watermark are outside the current delivery scope.

## Update an existing installation

Use the documented deployment update API or UI with the newly published immutable version. Preserve the existing deployment, its app database, installation scope, and secret references unless the approved change explicitly requires otherwise. Coordinate active app jobs according to the app's documented recovery behavior before an update. Verify the returned deployment state, selected route, and affected user workflow. Record the observed release digests and source provenance when the public target exposes them; no Docker, Kubernetes, or platform-host access is assumed. Reinstallation is not a substitute for an upgrade check.
