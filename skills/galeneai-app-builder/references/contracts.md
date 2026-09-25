# App contracts and versioned snapshots

Use the contract files in [contracts/](contracts/) as the public authoring reference:

- [Application manifest JSON Schema](contracts/application-manifest.schema.json) is the public authoring snapshot for new app versions.
- [OpenAPI snapshot](contracts/application-api.openapi.yaml) records the public package, validation, registry, import, availability, and tenant deployment routes used by this skill.
- [Snapshot lock](contracts/snapshot-lock.json) records the exact Platform Core commit, source files, and SHA-256 hashes of both exported contract files.
- [Public external-registry manifest example](contracts/examples/team-notes-manifest.json) and [multi-component archive-import request example](contracts/examples/multi-component-archive-import-manifest.json) use only fictional IDs and digests.

The lock pins Platform Core commit `a3026e0d7cfb09279765f7450476f040c85eb154`. These files are versioned contract artifacts; they contain no platform implementation code. When a contract changes, review the source at the exact committed revision, update the affected snapshot and source-file hashes, then update the app compatibility matrix with the new commit and contract hashes. The package tool rejects a compatibility record that does not match the pinned artifacts.

The schema is for authoring and offline checks. It cannot express every Pydantic cross-field rule, prove that a registry source exists and is usable, or authorize a tenant action. Before a direct version publication, call `POST /controlplane/application-manifests/validate` with `{package_slug, version, manifest}` using `controlplane.applications.manage`. A valid manifest returns `200 {valid: true, errors: []}`; an invalid one returns `422 {valid: false, errors: [{path, message, type}]}`. Paths include array indices. The read-only response never echoes the manifest or validation context. Core repeats validation when creating the immutable version, so the validator is a preflight, not a replacement for publication.

A direct new version must not contain legacy capability names such as `direct_tenant_db`, `redis`, `temporal`, or `oidc_client`, or `connectivity.outbound_hosts`. Old immutable manifests may be normalized for compatibility, but new publication rejects these values. `archive_import` targets are accepted only by the dedicated archive-import flow; the direct version validator and version-creation route reject them.

For publisher installation, use the documented Control Plane tenant catalog and application deployment endpoints with the required publisher permissions. Select the tenant explicitly from that catalog and verify the app deployment in that tenant. A publisher-authorized Control Plane flow is the supported delegated installation path, not a tenant-authorization bypass. If the user chooses tenant-scoped installation instead, use that tenant's available application catalog and tenant deployment API with a tenant-scoped token. In either flow, report the selected tenant slug with the returned deployment ID/status.
