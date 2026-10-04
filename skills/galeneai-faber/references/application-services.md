# Application services

## Contract status

The packaged manifest schema and focused OpenAPI pin Platform Core `ea864468d8f4ef1da3543dc37b960d2a4349de09` (Core 1.3.0), including manifest 1.0 service/resource requirements and internal endpoints, `/v1/services`, the eleven job-consent, inbox/preferences, resource and credential management routes, and installed MCP/owner consent contracts. Compare the relevant public contract with the explicit target before packaging or installation; tenant configuration, approvals and runtime readiness remain separate prerequisites. This is the final recorded contract source for the snapshot. A live target OpenAPI download cannot replace the versioned snapshot or its hashes. See [contracts](contracts.md).

## Declare intent in manifest 1.0

Set `app.requires_core` to `">=1.3,<2.0"` for new service releases and keep `schema_version` at `"1.0"`. Core 1.3 is the first release version assigned to this service contract; a Core 1.2 version alone cannot establish support for these fields. The installer/publication preflight checks target OpenAPI before mutations; see [the version barrier and source pin](contracts.md). Declare logical service roles in `service_requirements` and tenant resource roles in `resource_requirements`. These declarations request access; installation must separately approve service roles and bind resources.

A service entry contains:

- `role`: unique lowercase name matching `^[a-z][a-z0-9_-]{0,62}$`;
- `service` and nonempty unique `operations`: a family and operations from the catalog below;
- `resource_roles`: declared logical resource roles, default `[]`;
- `execution_modes`: `application`, `user`, or both, default `["application"]`;
- `required`: installation requires explicit approval when true, default false;
- `target_components`: backend/worker component names; `[]` selects all backend/worker components;
- `mcp_tools`: exact remote tool names for MCP invocation only, default `[]`.

A resource entry has a unique logical `role`, a `kind`, `access` (`read` by default), and `required` (false by default). Kinds are `filesystem`, `db_connector`, `mcp_connector`, and `notification_recipient`. Only filesystem supports `read_write`; other kinds are read-only. Resource roles referenced by a service must exist and have the correct kind. A required service cannot depend on optional resource declarations. Never put tenant UUIDs, email addresses, connector configuration, or credentials in these declarations.

| Family | Operations | Relevant bound resource |
|---|---|---|
| `web` | `search`, `fetch`, `browsing` | Writable filesystem for browser downloads |
| `sandbox` | `execute`, `stop` | Filesystem; read grants mount it read-only |
| `database_connectors` | `schema.read`, `query.read` | Database connector |
| `documents` | `extract`, `ocr`, `convert` | Writable source for processing; writable destination for conversion |
| `retrieval` | `search`, `index` | Filesystem with indexed/source documents |
| `inference` | `chat`, `embedding`, `transcribe` | Declared model role, selected separately |
| `filesystem` | `read`, `write`, `checkpoint` | Filesystem; write/checkpoint require `read_write` |
| `mcp` | `catalog`, `invoke` | MCP connector |
| `jobs` | `schedule` | Explicitly approved downstream work and consent, as described below |
| `notifications` | `send` | One or more declared notification recipients |

MCP `invoke` needs a nonempty `mcp_tools` allowlist without wildcards. Core validates tools and pins their approved schemas during binding approval; changed schemas require approval again. Catalog discovery does not authorize newly found tools. Trusted schema hashes belong to Core's internal binding metadata; installation requests and deployment responses expose only `resource_id` and `access`.

For inference, also declare `model_requirements` with the logical role and slot: `llm`/`chat`, `embedding`/`embedding`, or `stt`/`transcription` with audio input. Send `arguments.model_role`, never a provider key, URL, or arbitrary model ID. Core resolves the current tenant-authorized model binding and active embedding assignment for each call. Declare image modality for OCR's vision role when required. Usage is reported from actual upstream observations; unavailable usage must stay unavailable.

`chat` accepts optional `disable_reasoning_if_supported` (default false). With true, Core requests reasoning off only when the resolved model catalog has `thinking_control: "per_request"` and includes `"off"` in `reasoning_efforts`; otherwise provider behavior is unchanged. This flag does not select a model, override its catalog policy or guarantee a nonempty answer. Budget output tokens for the task and inspect `text` and `finish_reason` before claiming success; truncation is not a completed answer.

For an optional feature such as Assistant's conversation title generation, declare its own `llm` role with `requirement: "optional"`. Installation can proceed when that optional role is unavailable; the app must reflect the feature's unavailable state instead of treating installation as proof it can run. A required primary chat role remains a separate requirement. Select an authorized model binding through the installation controls; optional does not grant inference, invent a model fallback or make Assistant's technical title credential a generic app credential.

Keep app-owned `database_resources` and app `filesystem_resources` separate from resource bindings to existing tenant assets. Core service use does not require manufacturing a user, agent, or chat session.

Apps may also declare `internal_endpoints` for their own MCP tools or signed job
callbacks. Registration permits installed Core routing without a public route;
it creates no caller access. Suggest [installed application MCP](installed-application-mcp.md)
when specialized agents should use app business actions. It separates explicit
revocable offline owner consent from another app's own approved service authority.

## Installation and approval

Use the Console/Control Plane service approval UI or the verified deployment API. `install.py` accepts explicit repeated `--approved-service ROLE` selections and a `--service-bindings JSON_FILE` mapping after the committed-snapshot gate is met. Read [tooling](tooling.md#explicit-service-selections-at-installation) for local validation and tenant/publisher behavior; the tool never infers approval from required declarations.

Authorized operators choose resources from:

- `GET /controlplane/tenants/{tenant_id}/application-service-resources` with `controlplane.applications.deploy`;
- `GET /tenant/application-service-resources` with `application.install` or `application.update`.

Both catalog routes return HTTP 200 in the standard response envelope with `result` containing `{id, name, kind, access}` entries and `total` equal to the returned count. They are unpaginated and expose no credentials or MCP schema pins. Select IDs only from the catalog for the explicit target tenant. Core checks current resource authority again; a saved selection is not permanent access.

The deployment request supplies `approved_services` as logical service role names and `service_bindings` as resource-role mappings to `{resource_id, access}`. There are no automatic grants. Required approvals/bindings must be complete for installation and upgrade. Settings may revoke a required service without uninstalling the app; subsequent calls fail authorization. On PATCH, omit unchanged fields to preserve grants/bindings; an empty list/map explicitly changes the selection. See [examples](application-services-examples.md).

Notifications bind the actual tenant user UUID through a `notification_recipient` resource at installation. The manifest declares only the logical recipient role. Core checks an active recipient, current caller authority, and notification preferences. Never accept arbitrary recipient addresses or wildcard recipient grants.

## Per-component credentials

Core provisions an individual managed credential only for each approved backend/worker target. It injects:

- `GALENE_APPLICATION_SERVICE_TOKEN`: secret bootstrap credential;
- `GALENE_APPLICATION_DEPLOYMENT_ID`: deployment UUID;
- `GALENE_APPLICATION_SERVICE_CONTEXT`: JSON describing this component's approved requirements and grant revision.

These names are reserved: do not redeclare them in `env_schema`, request them from an installer, copy them into app artifacts, or expose them to a frontend. Discover the public Core API base through [API discovery](api-discovery.md); do not guess a generated service API URL variable. The context helps the app present its configuration; Core remains the authorization authority.

Exchange the bootstrap credential at `POST /v1/services/token` using `{bootstrap_token}`. The token DTO contains `{access_token, token_type: "Bearer", expires_in}`. Use the short access token as `Authorization: Bearer ...` for service operations. Current source sets `expires_in` to 300 seconds; renew using the returned lifetime, not a hardcoded timer. Keep tokens server-side and acquire a fresh access token when grants change. Do not send the bootstrap credential to another API or use it as a tenant-user token.

Revocation, suspension, uninstall, component targeting, tenant state, and grant revision are checked by Core. Credentials are not provider credentials and do not authorize ordinary tenant APIs.

Rotation uses ordinary management authentication, never an application bearer:

| Route | Permission |
|---|---|
| `POST /tenant/applications/deployments/{deployment_id}/service-credentials/rotate` | `application.update` |
| `POST /controlplane/tenants/{tenant_id}/application-deployments/{deployment_id}/service-credentials/rotate` | `controlplane.applications.deploy` |

Both routes return HTTP 200 with `result: {deployment_id, service_grant_revision}` in the standard response envelope. They take no credential request body and reveal no new secret. Core increments the revision, invalidates previous tokens and stored operation/job authority, and requests redeployment to inject new bootstrap credentials. Observe deployment readiness separately. Each repeat rotates again; these routes have no idempotency key. An unavailable/wrong-tenant deployment returns 404; a deployment without `desired_status: "deployed"` or its immutable version returns 409.

## User delegation and offline consent

For a user-mode service call, keep the application bearer in `Authorization` and pass the actual signed-in tenant user's bearer in `X-Galene-User-Authorization: Bearer ...`. Core verifies that user and tenant and intersects resource authority with the user's current permissions. A user header selects user mode; that mode must be in the approved requirement. Never send a user UUID as authorization or substitute a service account.

Keep the same delegated header on grants, submission, polling, cancellation and artifact reads. The verified user identity remains the operation actor across database scopes; Core resolves the active user and current tenant-local resource ACLs again. Omitting that header switches to application mode and does not recover that user's operation. A revoked/inactive user or changed permission cannot borrow the original request's authority.

Delegation expires with the verified user token, including while work is queued. Surface `user_delegation_expired` and obtain the user's supported fresh authentication before explicitly retrying failed work. Reusing a key recovers its persisted operation; it does not restart a terminal failure. Personal MCP OAuth access requires that actual user's delegation; application mode cannot borrow personal tokens.

User-mode scheduled work requires explicit offline consent for its exact immutable target operation, bound resources and lifetime. Create the schedule through `jobs.schedule` with verified user delegation, then have its creator review/approve it using ordinary tenant authentication at `GET /application-jobs/{job_id}` and `POST /application-jobs/{job_id}/approve`; consent expiry is between one minute and 30 days. Application-mode schedules use their approved application authority. Neither mode retains a user bearer for future work. Follow [jobs, consent and callbacks](application-jobs-notifications.md) for exact bodies, permissions, job states and signature verification.

## Durable operations

The public service family uses these operation routes:

| Route | Purpose |
|---|---|
| `GET /v1/services/grants` | Read the component's current grants |
| `POST /v1/services/operations` | Submit a service operation |
| `GET /v1/services/operations` | Recover/list operations visible to the current app actor |
| `GET /v1/services/operations/{id}` | Poll a persisted operation |
| `POST /v1/services/operations/{id}/cancel` | Request cancellation |
| `GET /v1/services/operations/{id}/artifacts/{name}` | Retrieve the authorized operation artifact |

Token, grant and operation endpoints return direct JSON, without the installation API's `WSResponse` envelope. `GET /grants` returns `{schema_version, deployment_id, component, grant_revision, services, resources, limits}`; `services` contains the approved requirements usable by this component in the current execution mode, `resources` contains public bindings for those roles, and `limits.max_argument_bytes` reports the argument limit. It is a current view, not a durable authorization promise.

The submission DTO is `{service_role, operation, arguments}`. It contains no service-family override, tenant, deployment, user, provider credentials, or grant metadata. Core resolves the approved role. The operation DTO contains `id`, `service`, `operation`, `status`, `cancel_requested`, `result`, `error`, `created_at`, and `updated_at`. Status is `queued`, `running`, `succeeded`, `failed`, or `cancelled`; `result` and `error` are nullable. Errors have safe codes/messages; do not render or log arbitrary upstream bodies.

Store the returned operation ID in the app's own workflow metadata and recover it after refresh. Show the actual persisted state. `cancel_requested` alone does not mean cancellation finished. Some document/index work has downstream processing state: inspect its returned lifecycle data before presenting a usable extraction/index. A queued submission is not completed work.

Submission requires `Idempotency-Key`: 1–200 ASCII characters from `!` through `~`, with no spaces. Core scopes the key to deployment, component and actor, and hashes the service role, operation, arguments and grant revision. An identical retry under the same grants returns the persisted operation with HTTP 202; changing the body or grant revision under that key returns HTTP 409 `idempotency_conflict`. Store the key before submitting. Recover an uncertain request using the same key/body; never create a fresh key solely to escape an uncertain side effect.

The list returns a direct array, newest first, with `limit` default 25 and range 1–100. There is no cursor or total in this contract; do not claim the recent list is a complete history. Reads/list/cancel/artifact access are scoped to the same deployment, component and actor and current grant revision. Switching from application mode to a delegated user changes the actor. A previous-grant operation cannot be recovered by simply acquiring a new token; show the changed authority to the installer.

Cancel returns HTTP 202 with the operation DTO. It marks `cancel_requested` for nonterminal work and dispatches the request; terminal work stays terminal. Poll for the final status. Completed effects are not undone. Artifacts are byte responses, available only after `succeeded`: `file` reads a result artifact from a currently bound filesystem; `web`, `sandbox` and `result` read the exact recorded JSON snapshot if present. A storage key in the result is not a URL and must not be fetched directly. An absent artifact returns `artifact_not_found`, and unfinished work returns `result_not_ready`. Token/artifact responses use `Cache-Control: no-store`.

Auth failures include `invalid_application_credential`, `invalid_application_token`, `application_credential_revoked`, `application_grants_changed`, `application_inactive`, and `tenant_inactive`. Authorization/configuration failures include `service_not_granted`, `operation_not_granted`, `resource_not_configured`, `resource_access_denied`, `model_role_unavailable`, and `model_role_denied`. Error HTTP details use `{code, message}`. On invalid/expired access tokens, refresh through the bootstrap exchange; on revocation or denied access, show the missing approval and refer it to the authorized installer. Do not loop refresh to bypass denial. Surface provider/capacity/processing failures as recoverable workflow errors according to the final public contract.

## Browser and sandbox lifecycle

Browser contexts and warm sandbox runtimes belong to the exact tenant, deployment, component, actor and recorded authority. A context ID is a handle, not an access grant. Core rechecks authority during work and reconciles retained runtimes after revocation, rotation, binding changes, delegation/consent expiry, suspension or uninstall. Cleanup uses persisted ownership to contain the old runtime without granting new application access or touching a replacement owner.

For a browser, submit `web.browsing` with `action: "close"` and its returned `context_id`, then poll that close operation. Show closed only after `succeeded` with `result.status: "closed"`. Public operation cancellation requests interruption; it does not itself attest provider closure. Core retains cleanup uncertainty when the old browser worker/provider does not acknowledge closure, including `browser_provider_close_unconfirmed`; loss of a lease or worker is not proof that the provider closed.

Sandbox execution requires a configured, enabled tenant sandbox policy in addition to the application service approval and filesystem binding. `sandbox_not_configured` means that prerequisite is missing; `sandbox_disabled` means the tenant policy disables execution. Ask the authorized tenant operator to configure/enable it. Core refuses execution before generation creation, retirement or sandbox transport when that prerequisite is absent; acquiring another token or creating another operation key does not fix the policy. A sandbox operation can fail with `tenant_concurrency_exhausted` when admission reaches the tenant sandbox concurrency limit; that failure does not imply that a writer started. Other transport failures remain `sandbox_unavailable`.

To explicitly stop a warm sandbox, submit `sandbox.stop` through `POST /v1/services/operations` with `arguments: {target_operation_id: <original execute operation UUID>}`. Use the same sandbox service role/component/actor as the original execute, with current approval for both `execute` and `stop` and the same authorized resource bindings. For user mode, retain verified delegation from that same actual user; an application bearer cannot substitute for the user actor. Core reauthorizes the original execute under current grants and user ACLs. A target UUID grants no authority, and this endpoint cannot borrow Core's internal cleanup authority after revocation or rotation.

The stop is a separate durable operation with its own persisted idempotency key. Poll its operation ID and show stopped only after `succeeded` with `result.status: "stopped"`; the result identifies `target_operation_id`, the original runtime's `context_id`, and `filesystem_role`. An already terminal execute retains its status, result/error and original artifacts. A nonterminal execute is cancelled only after confirmed exact-owner containment. Stop attests containment, not retained-volume cleanup. Verify live stop acceptance for the selected deployment separately from this source contract.

If another warm execute replaced the target as that runtime's source operation, stop fails with `stale_target` instead of stopping the replacement. Authority mismatches are denied, including `operation_grants_changed` and `target_authority_mismatch`. Repeating the same body/key recovers the original stop operation under the same grant revision; changing the target or grants with that key produces `idempotency_conflict`. A retry for an already retired original generation must not stop a newer generation. Preserve the original target/key when a result is uncertain; do not automatically retarget the latest execute. Polling stays `GET /v1/services/operations/{id}` and interruption stays `POST /v1/services/operations/{id}/cancel`; do not declare `sandbox.status` or `sandbox.cancel` as service operations.

Sandbox operation completion/cancellation and runtime containment are separate. Core confirms retirement only for the exact persisted owner, runtime identity and generation, using a permanent fence and attested containment (`absent` or `stopped`). Attested absence under that fence can confirm retirement even when the earlier startup was never acknowledged. Pending startup/provider work, a crash without settled containment evidence or loss of the fence leaves cleanup unconfirmed. `runtime_cleanup_pending` blocks a new execution while the previous owned runtime remains pending/failed cleanup; confirmed permanent retirement permits a new generation. `sandbox_startup_inflight_unconfirmed` and `sandbox_cleanup_unconfirmed` preserve unresolved containment. Retained VFS/root volume cleanup proceeds independently and is not attested complete by retirement or an operation terminal status. These codes describe Core lifecycle failures, not additional application endpoints. Do not call private sandbox lifecycle APIs or present internal cleanup as complete from an operation's terminal status alone.

An interrupted operation may report `operation_outcome_uncertain` when its external effect cannot be confirmed; runtime cleanup has separate persisted state and may remain unconfirmed after an operation is `succeeded`, `failed` or `cancelled`. Present that uncertainty and preserve the operation ID/idempotency key; a fresh submission is not a safe automatic recovery. After authority is removed, operation reads may themselves be denied. Do not fabricate a closed state from that denial; refer unresolved containment to the platform operator.

## Choose each service directly

Use service arguments and results from the verified snapshot; [examples](application-services-examples.md) provide concrete source-backed request bodies. Tenant defaults and provider configuration are operator responsibilities.

- Web search/fetch/browsing invoke configured web services directly. They do not require or silently run inference. Browsing actions are deterministic and retain an app-owned browser context; downloads need a writable bound filesystem.
- Sandbox execution uses the tenant-approved sandbox image/policy, bounded commands, and an app-owned context with its bound filesystem. Use public `sandbox.stop` for explicit warm-runtime containment and canonical operation cancellation for interruption; never call the executor's internal lifecycle endpoints.
- Database discovery/query uses bound connectors and parameterized read-only SQL. Core returns bounded results and enforces tenant capacity; apps never receive database credentials.
- Documents reuse Core extraction/OCR/conversion. Source and destination paths stay within bound filesystems. OCR uses an approved model role; conversion writes a new path with writable authority.
- Retrieval uses indexed documents from bound filesystems and the active embedding authority; vector, multimodal, and graph modes have their own tenant prerequisites. Index completion must reflect real downstream processing.
- Inference is explicit chat, embedding, or transcription against a declared model role. Provider configuration and accounting remain Core-owned.
- Filesystem operations use relative normalized paths under the bound resource. Writes and checkpoints require write access; raw write cannot overwrite a tracked document.
- MCP invokes only the exact approved tool allowlist with matching current schemas. Connector secrets remain inside Core.
- Jobs schedule only explicitly authorized work and consent; job lifecycle is separate from the submission operation lifecycle.
- Notifications target approved recipient bindings and respect recipient-owned channel preferences. Read [notification inbox, receipt and SMTP prerequisites](application-jobs-notifications.md#send-to-approved-recipients): internal delivery is a real inbox record, while email uses the tenant SMTP broker. Authenticated SMTP configured before that broker requires securely saving its password again.

## Focused acceptance

After review, verify one representative installed workflow on the assigned beta stack and the directly affected authorization regression. Check expired/revoked credentials, denied service/operation/resource scope, user/application separation, recovery with the same operation ID, and only the side effects the app needs. Keep stack-free app tests isolated from platform runtime. Do not claim deployment or success from authored examples, a queued operation, or offline schema validation. Kubernetes checks and backup/support/watermark are outside the current delivery scope.
