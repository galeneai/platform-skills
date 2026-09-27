# Integrated registry releases

The pinned Platform Core contract in [the snapshot lock](contracts/snapshot-lock.json) supports one archive-import operation for a release with up to 64 `archive_import` components. Every imported component in that operation must use the same enabled, verified internal `RegistrySource`. A manifest may also contain components that already use immutable `image_source` references.

The import archive contains image layers and image-index metadata only. It is uploaded separately from the deterministic bundle produced by `scripts/package.py`; that bundle contains the manifest, compatibility record, release metadata, and optional release notes, never container images, registry credentials, or the archive itself.

## Build and select multiple images

Build and tag every component image locally, then create one Docker save archive with all imported images. For example:

```sh
docker build -t acme/team-notes-web:1.2.0 ./web
docker build -t acme/team-notes-api:1.2.0 ./api
docker save -o release-images.tar acme/team-notes-web:1.2.0 acme/team-notes-api:1.2.0
```

Use these tags to make the archive inspectable; the published version is pinned by the SHA-256 digests Core records after copying each selected image. Keep the archive outside the app release bundle and don't put auth files, registry credentials, or private config into it. Use production build stages and include only files needed by the images to keep the archive size manageable.

Core accepts Docker-save archives and OCI image-layout tar archives. During inspection, Core reads the Docker `manifest.json` `RepoTags`; it reports candidates such as `docker-0` and `docker-1` with their tag reference and platform. OCI candidates must have a valid `org.opencontainers.image.ref.name` annotation in each `index.json` descriptor; Core reports them as IDs such as `oci-0`. Inspection can list up to 64 candidate images. The archive upload is capped at 20 GiB, and the worker enforces its configured expanded-size limit (20 GiB by default). A release may declare up to 64 imported components.

Match the inspected candidate reference to the component name, then submit one explicit mapping for each component under `archive_import`. For example, **only if the inspection response confirms these IDs and references**:

```json
{
  "mappings": [
    {"component_name": "web", "candidate_id": "docker-0"},
    {"component_name": "api", "candidate_id": "docker-1"}
  ]
}
```

Never assume that candidate IDs follow the order of command-line arguments. Read `candidate_images` from the server's import status, select by the image tag/reference and platform that match the manifest component, and use only the returned `candidate_id`. The mapping must include every imported component exactly once. Reusing one inspected candidate for multiple components is supported when that is the intended release.

## Atomic release flow

1. Ensure the app package exists. Select the target tenant explicitly; the archive-import request includes its tenant ID.
2. Call `POST /controlplane/applications/{package_id}/archive-imports` with JSON metadata `{tenant_id, version, manifest, archive_filename, release_notes?}`. This creates the import; it does not receive image bytes. The response identifies the import job and target repository for each imported component.
3. Upload the archive separately through multipart staging: call `POST /controlplane/application-archive-imports/{import_id}/parts/{part_number}` for each part to receive a short-lived upload URL; upload bytes to each returned URL; then call `POST /controlplane/application-archive-imports/{import_id}/complete` with the uploaded-part receipts and total archive size (and optional archive SHA-256). Never log or publish presigned URLs.
4. Poll `GET /controlplane/application-archive-imports/{import_id}` until archive inspection completes. Read `component_names` and `candidate_images`. A single imported component with one candidate may be selected automatically. Otherwise call `POST /controlplane/application-archive-imports/{import_id}/select-images` with one `{component_name, candidate_id}` mapping per imported component. Every imported component must be mapped exactly once; the same inspected candidate may be reused for more than one component. The legacy `/select-image` route is only for one-component imports.
5. Core copies each mapped image to its component repository and records a SHA-256 digest. The immutable package version and its availability for the selected tenant become visible together only after every image copy succeeds. Check `result_version_id`, `component_mappings`, and `component_digests` in the final import response before installing.
6. A retry keeps the saved mapping and successful digests. Cancel or failed partial copies do not publish a version or tenant availability. Cleanup and registry garbage collection are separate administrative operations.

Core keeps registry credentials in server-side secret references. Import jobs access them only in a protected temporary auth file. Do not place registry credentials in app files, CLI arguments, examples, or logs. Use a verified source that already exists; creating one is a separate publisher action.

After import completion, use [the offline import verifier](tooling.md#import-verification) with the manifest, a protected saved final-status response, and the intended full image references. Do not guess candidate IDs from archive order: choose the server-returned candidate whose reference and platform match each component. A successful offline check still requires a separate installation and tenant-runtime verification.

## Older Core snapshots

Use only the routes and semantics present in the selected Core commit's snapshot. If a Core snapshot lacks multi-component mapping or atomic version-plus-availability publication, do not claim those guarantees or simulate one release with separate imports. For a multi-component app, use an owner-managed, verified external OCI source with immutable digest references, or defer publication. Use an older single-component import flow only for a genuinely single-component app when its pinned snapshot documents that flow.

## Runtime parity

The integrated registry transports component images; it does not establish app behavior or runtime compatibility. Verify app behavior and manifest support on Compose and Kubernetes when both adapters are in scope. The release compatibility matrix records each adapter's result separately.
