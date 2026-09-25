# Integrated registry releases

The pinned Platform Core contract in [the snapshot lock](contracts/snapshot-lock.json) supports one archive-import operation for a release with up to 64 `archive_import` components. Every imported component in that operation must use the same enabled, verified internal `RegistrySource`. A manifest may also contain components that already use immutable `image_source` references.

## Atomic release flow

1. Ensure the app package exists. Select the target tenant explicitly; the archive-import request includes its tenant ID.
2. Call `POST /controlplane/applications/{package_id}/archive-imports` with `{tenant_id, version, manifest, archive_filename, release_notes?}`. The response identifies the import job and target repository for each imported component.
3. Upload the archive through the documented multipart flow: request a part URL, upload each part to the returned URL, then call the completion route with the completed parts and archive size.
4. Poll `GET /controlplane/application-archive-imports/{import_id}` until archive inspection completes. Read `component_names` and `candidate_images`. A single imported component with one candidate may be selected automatically. Otherwise call `POST /controlplane/application-archive-imports/{import_id}/select-images` with one `{component_name, candidate_id}` mapping per imported component. Every imported component must be mapped exactly once; the same inspected candidate may be reused for more than one component. The legacy `/select-image` route is only for one-component imports.
5. Core copies each mapped image to its component repository and records a SHA-256 digest. The immutable package version and its availability for the selected tenant become visible together only after every image copy succeeds. Check `result_version_id`, `component_mappings`, and `component_digests` in the final import response before installing.
6. A retry keeps the saved mapping and successful digests. Cancel or failed partial copies do not publish a version or tenant availability. Cleanup and registry garbage collection are separate administrative operations.

Core keeps registry credentials in server-side secret references. Import jobs access them only in a protected temporary auth file. Do not place registry credentials in app files, CLI arguments, examples, or logs. Use a verified source that already exists; creating one is a separate publisher action.

## Older Core snapshots

Use only the routes and semantics present in the selected Core commit's snapshot. If a Core snapshot lacks multi-component mapping or atomic version-plus-availability publication, do not claim those guarantees or simulate one release with separate imports. For a multi-component app, use an owner-managed, verified external OCI source with immutable digest references, or defer publication. Use an older single-component import flow only for a genuinely single-component app when its pinned snapshot documents that flow.

## Runtime parity

The integrated registry transports component images; it does not establish app behavior or runtime compatibility. Verify app behavior and manifest support on Compose and Kubernetes when both adapters are in scope. The release compatibility matrix records each adapter's result separately.
