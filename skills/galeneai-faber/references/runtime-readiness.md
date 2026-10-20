# Runtime readiness on Kubernetes and Compose

Use this guide before declaring that an app runs on Arethusa/Kubernetes. An app that passes its local tests and a Compose run can still fail on Kubernetes with the platform's real injected environment and its service-mesh sidecar. Every item below caused a failed first installation of a real app; each is cheap to build in and expensive to find on the cluster.

## 1. The injected database URL is libpq-style

The URL injected at the manifest-selected variable (normally `DATABASE_URL`) is a PostgreSQL URL whose query may carry libpq options such as `sslmode` and `sslrootcert`. Drivers do not agree on them:

- psycopg understands libpq options.
- asyncpg does not: passing `sslmode` through SQLAlchemy ends in `TypeError: connect() got an unexpected keyword argument 'sslmode'`, and the app never starts.

Parse the URL in one module that builds every engine (async, sync, migrations):

- accept `postgres://` and `postgresql://`, with or without a `+driver`;
- strip `sslmode`, `sslrootcert`, `sslcert`, `sslkey`, `sslpassword` and any other option the driver rejects, and translate them: `disable`, `allow` and `prefer` map to the driver's equivalents, `require` means encrypted without certificate verification (as libpq), `verify-ca` and `verify-full` build a TLS context from `sslrootcert` (or the system roots) and `verify-full` also checks the host name;
- never let a database error crash the process into a restart loop: retry with backoff, keep the liveness endpoint answering, and report the cause on readiness;
- log the exception type plus the app's own safe diagnosis as fields (driver, ssl mode in use, host and port, the option names it dropped), following [logging](logging.md); never the library message, which can echo credentials. A bare class name alone (`TypeError`) hid this error for hours.

Test it without a live server by feeding URLs with each `sslmode` form through the engine factory and checking `engine.dialect.create_connect_args(engine.url)` against the driver's accepted keywords, then confirm once on the target.

## 2. Behind the service mesh

Pods on Kubernetes run with an Istio/Envoy sidecar. The kubelet's probes reach the app through the sidecar as plain HTTP with `Host` set to the pod IP and no forwarded headers.

- **nginx proxies HTTP/1.0 by default** and Envoy answers `426 Upgrade Required`. In every `location` with `proxy_pass` set `proxy_http_version 1.1;` and `proxy_set_header Connection "";`. A symptom is a web container whose probes fail with 426 and restarts endlessly while the backend is healthy.
- **Liveness must be cheap and independent**: it must not call the backend, the database, a model or the bootstrap. Readiness may depend on them, and its failure body should say why in plain words (an unreachable status page hides the reason otherwise).
- Health endpoints must not depend on the public origin, HTTPS headers or a signed-in user.
- Listen on `0.0.0.0`, run as a non-root user and write only to paths that user owns. A hostname in `proxy_pass` is resolved when nginx starts: make sure the dependency exists, or resolve at request time.

## 3. Configuration is derived, not typed

A non-technical installer must not have to enter anything the platform already knows.

- For every component with `connectivity.depends_on`, the platform injects `GALENE_COMPONENT_<NAME>_URL` (name upper-cased, `-` as `_`) with the dependency's internal `http://host:port` URL. Use it as the default backend/upstream origin of a web component instead of a required variable.
- With the `identity_provider` capability the platform injects `GALENE_TENANT_AUTH_CONFIG_URL` and `GALENE_TENANT_IDP_*`. The tenant slug and the public Core origin can be derived from the auth config URL. Target the capability at every component that needs them, workers included: a component not listed gets no injection.
- Do not assume more is injected. A typed manifest gets no installation id and no tenant UUID (`GALENE_APPLICATION_DEPLOYMENT_ID` may be absent): generate a UUID once and keep it in the app database. Derive the public origin from `Host` and `X-Forwarded-*`, and keep an explicit variable only as an override.
- Generate secrets such as a session key on first start and persist them in the app database; never ask the installer for them.
- Never ship lab values as defaults (tenant slugs, hostnames of a test environment, approval references). A variable is `required` only when no sensible default or derivation exists.
- Say in plain words when something cannot be derived (sign-in page, readiness body), not with a bare 503.

## 4. Persistent volumes need a storage class

A `persistent_volume` becomes a PVC. The platform owns the storage class: unless one is set, the claim uses the cluster default, and a cluster without a default class leaves the pod `Pending` forever (`no persistent volumes available for this claim and no storage class is set`).

- Prefer the app database or object storage. Use a volume only when the data is large, needed after restarts and cannot live there, and document the prerequisite.
- Data that can be rebuilt (extracted text, thumbnails, exports) belongs in container-local paths. Rebuild it on cold start and make readiness check that the files exist, so a restarted pod does not report ready with empty paths.
- The worker should not need the volume; a volume is mounted by the component that declares it.

## 5. Apps meant to be shown by non-technical people

- Load the demo data from the image in an idempotent, lock-guarded, resumable first-start bootstrap. No download, shell, browser automation or operator step.
- Apps have no service identity. Work that needs the user's Core token (filesystem, RAG ingestion, embeddings) runs at the first sign-in of a user allowed to manage the corpus, with visible progress. The app must be useful before it finishes.
- Show results that were not produced by a model as such ("pre-computed"), and offer a live run when a model is bound. Do not invent model output from real documents.
- Bundle only data whose redistribution is cleared and ship a NOTICE with source and licence per file.
- Give demo budgets and ceilings generous defaults and reset them with the demo reset.

## 6. Verify on the target before claiming parity

Local tests and a Compose run do not establish Kubernetes behaviour. Before declaring the release ready:

1. Install it once on a Kubernetes target and check that every pod is Ready with zero restarts after a few minutes.
2. Read `kubectl describe` events and the previous-container logs of any restart: `Unhealthy`, `FailedScheduling` and `FailedBinding` explain most failures.
3. Confirm database connection, probes through the sidecar, the bootstrap reaching its ready state and a sign-in from the public hostname.
4. Only then record the Kubernetes adapter as verified in the compatibility matrix; keep `not_requested` or `not_verified` otherwise.

`scripts/validate.py` prints non-blocking warnings for the manifest patterns above that it can see offline (a volume without `storage_class`, required variables with no default, required upstream origins that the platform injects).
