# Application jobs, callbacks and notifications

Read [application services](application-services.md) first. This guide follows the packaged Platform Core `663b69cc602264a00090a60b8bb6b52c4f99efb9` contract and uses probe app `00a2176d09adc191b23ad00c59c5f965a7de98e3` for concrete usage. Verify the [target contract and prerequisites](application-services.md#contract-status) before publishing or installing a service-dependent app; app builders use the public contract without requiring Core source access. Examples are not evidence of runtime delivery.

The eleven ordinary management routes are documented in that Core revision: three job-consent routes and four inbox/preferences routes below, plus the two resource catalogs and two credential-rotation routes in [installation and credentials](application-services.md#installation-and-approval). They use their stated tenant or Control Plane authentication; `/v1/services` application credentials do not replace it. All eleven are included in the packaged focused OpenAPI.

## Schedule a declared operation

Submit `{service_role: <jobs role>, operation: "schedule", arguments: {...}}` through `POST /v1/services/operations` with the application bearer and persisted `Idempotency-Key`. `arguments.action` is `create` by default; supported actions are `create`, `list`, `get`, `pause`, `resume`, `delete` and `run`.

Creation arguments are:

- `name`: nonempty string, at most 200 characters;
- `service_role` and `operation`: the separately approved target role/operation;
- `arguments`: immutable target-operation arguments, an object of at most 64 KiB;
- `calendar`: `{timezone, dtstart, rrules, rdates, exdates}`;
- optional `overlap_policy: "buffer_one"` and `misfire_policy: "coalesce"`, the only supported policies;
- optional `callback: {url, events}` as described below.

Use an explicit IANA timezone. `dtstart` is a local ISO datetime **without** an offset; `rrules` are recurrence strings; `rdates`/`exdates` must be explicit datetimes with an offset (Core normalizes them to the calendar timezone). Core validates/normalizes the recurrence and requires a future occurrence. Jobs cannot schedule another `jobs` operation. Both the scheduling role and target role must allow the caller's mode and component; choosing the target does not grant it.

The completed scheduling operation's `result` is the job snapshot: `job_id`, `name`, `status`, `reason_code`, `execution_mode`, `target_service_role`, `target_operation`, `target_arguments`, `calendar`, `scope`, `next_due_at`, `overlap_policy`, `misfire_policy`, `active_occurrence`, `last_result`, and `callback`. Store `job_id` separately from the outer operation ID. Successful creation means the schedule exists, not that a target occurrence completed.

Use `{action, job_id}` for `get`, `pause`, `resume`, `delete`, or `run`. `list` returns `{jobs: [...]}` for up to 100 nondeleted jobs owned by the current deployment/component/actor. `get` adds the latest 20 `callback_deliveries`, each with `event_id`, `operation_id`, `event`, `status`, `attempts`, and `last_error`. There is no arbitrary calendar/target update action: create a newly reviewed schedule when its immutable work changes.

One occurrence may run and one missed tick is buffered; missed ticks are coalesced. `active_occurrence.operation_id` identifies the actual child service operation, while `last_result` records its terminal status and occurrence key. Poll the job and child operation; an outer `run` success alone is not a completed target effect. `run` requests an immediate occurrence and returns `job_overlap` if one is already active/pending. Preserve the outer submission's key/body when retrying it.

Job states include `pending_consent`, `active`, `paused`, `blocked`, `completed`, and `deleted`. `reason_code` explains blocked authority. Pause clears buffered work; delete also revokes stored user consent. Neither undoes completed effects. Current job status/consent is rechecked before queued child effects. Use the child operation's public cancellation route when cancellation of that operation is required, then observe its terminal status. A changed credential/grant requires recreating the job; renewing an access token does not restore the old scope. Core limits each deployment/component to 100 schedules that are not deleted/completed.

## Approve offline user work

An application-mode schedule starts `active` under its approved application authority. A user-mode schedule is created with the application bearer plus `X-Galene-User-Authorization` and starts `pending_consent`. It does not retain the user's bearer for future work.

For user-mode jobs, show the actual reviewed target arguments, calendar and scope to the creator. The following routes use the creator's **ordinary tenant bearer** in `Authorization`; application credentials cannot approve consent:

| Route | Permission | Direct JSON result |
|---|---|---|
| `GET /application-jobs/{job_id}` | `application_job.get` | Job snapshot plus `offline_delegation` |
| `POST /application-jobs/{job_id}/approve` | `application_job.approve` | `{job_id, status, expires_at}` |
| `POST /application-jobs/{job_id}/revoke` | `application_job.revoke` | `{job_id, status, revoked: true}` |

Approve with `{expires_at, scope}`. Copy the **complete** `scope` from GET, including credential, grant revision, target service/operation and bound resources; never synthesize it from the manifest. `expires_at` must include a timezone and be between one minute and 30 days from approval. Core rejects a changed scope with HTTP 409 `job_scope_changed`, checks current app access, target mode and resource ACLs, and records a revocable grant for that specific creator/job. Existing consent is reported as `{expires_at, revoked_at}`, or null.

Core rechecks the active user, app access, consent expiry/revocation and exact scope before offline work. Expired/revoked consent returns `offline_delegation_required` and can block the schedule. Revocation remains available to the creator after app access or credentials are removed, subject to the route's ordinary user permission. It pauses future work, clears the pending occurrence and invalidates queued authority; it is not rollback of already completed work. Approval requires an explicit user decision, not a silent BFF action.

## Verify job callbacks

Creation can subscribe `callback.events` to `job.operation.completed` and/or `job.operation.failed`; omission selects both. The destination must be public HTTPS without credentials or a fragment and pass Core egress checks. Private/local destinations and redirects are not a supported callback workaround. Keep the callback handler reachable on the installed app backend's approved public route.

The job snapshot returns `callback: {url, events, verification_key, signature_algorithm: "Ed25519"}`. Store the verification key with the known job identity obtained through the authenticated service API. Core keeps the private key. The callback JSON contains `{event_id, event, job_id, operation_id, status}`; completed means `succeeded`, and failed covers `failed` or `cancelled`. It carries no operation result or secret.

Headers are `X-Galene-Event-Id`, `X-Galene-Event-Timestamp` (Unix seconds), `X-Galene-Event-Signature` (base64 signature), and `X-Galene-Signature-Algorithm: Ed25519`. The signed bytes are:

```text
UTF8(event_id + "." + timestamp + ".") + canonical_JSON_body_bytes
```

Core serializes the body with sorted keys, compact separators and UTF-8 (`ensure_ascii=False`). Verify the exact received body bytes with the stored job key; check the algorithm, known job, event/header identity and supported event/status pair before acting. Apply a bounded timestamp window; the probe uses five minutes, which is a receiver policy rather than a Core token lifetime. Persist event-ID deduplication and a payload fingerprint atomically with the app's resulting action. Accept an already verified duplicate without repeating its effect; reject the same ID with changed payload. Return 2xx only after durable receipt. See [examples](application-services-examples.md#signed-callback-receiver).

Callbacks have stable event IDs and may be delivered again after transport/worker loss. Core retries transient failures, 408, 429 and 5xx with bounded backoff, at most five attempts; other non-2xx responses fail delivery. Paused/deleted/blocked/pending-consent jobs do not deliver new callbacks, and current authority is checked again before dispatch. Observe `callback_deliveries`; do not claim a successful child operation proves callback delivery or vice versa.

## Send to approved recipients

Declare `notifications.send` with one or more `notification_recipient` resource roles, each bound read-only to an active target tenant user at installation. Submit `{action: "send", channel, recipient_roles, title, body}` as operation arguments; action defaults to send and channel defaults to internal. `recipient_roles` names 1–20 bound logical roles. `title` is nonempty, at most 200 characters, without newlines; `body` is nonempty and at most 16,000 characters. Arbitrary email addresses, recipient UUID lists and tenant overrides are rejected.

Application mode addresses explicitly bound recipients. User-delegated mode may address only the bound current user. Core rechecks recipients, preferences and authority immediately before effects. Internal recipients also need `notification.list`. Channel discovery uses `{action: "channels"}` on the same approved send role and returns `{channels: [{channel: "internal", configured: true}, {channel: "email", configured, reason_code?}]}`. This describes transport configuration, not recipient permission or consent.

A successful send returns `{deliveries: [{delivery_id, recipient_user_id, channel, status}]}`. Internal status `delivered` means the real notification record exists. Email status `sent` means SMTP dispatch was accepted, not mailbox receipt. IDs are stable per operation/recipient/channel, so retry the same outer operation rather than creating duplicate sends. Core enforces 100 delivery records per deployment/component in a rolling hour. Disabled preferences return `notification_preference_denied`; unavailable recipients, channel configuration, quota or uncertain delivery have distinct safe errors.

### Recipient inbox and preferences

Use the recipient's ordinary tenant bearer; keep these endpoints separate from application service credentials. Responses are direct JSON.

| Route | Permission | Result |
|---|---|---|
| `GET /application-notifications?limit=100` | `notification.list` | `{notifications: [...]}`, newest first; limit 1–100, default 100 |
| `POST /application-notifications/{notification_id}/read` | `notification.read` | The recipient's notification item; repeating is idempotent |
| `GET /application-notifications/preferences/{deployment_id}` | `notification.list` | `{deployment_id, internal_enabled, email_enabled}` |
| `PUT /application-notifications/preferences/{deployment_id}` | `notification.read` | Same preference result after updating both booleans |

Each inbox item contains `notification_id`, `operation_id`, `title`, nullable `body`, `is_read`, and `created_at`. The inbox shows only application-operation records addressed to that user. A foreign/nonexistent notification returns `notification_not_found`. Preferences are recipient-owned per tenant deployment; missing preferences default both channels to enabled, and app arguments cannot override them. PUT takes `{internal_enabled, email_enabled}`. A foreign deployment returns `deployment_not_found`.

For real internal receipt, match the sender's `delivery_id` to inbox `notification_id` and its operation ID to inbox `operation_id`, as the probe receipt verifier does. A sender result alone does not prove the recipient can read that record. Do not claim a complete history from this bounded, unpaginated inbox.

### Tenant SMTP broker prerequisite

Core sends application email through the **tenant's** SMTP settings and current recipient identity, using its own encrypted password broker. Apps receive neither SMTP credentials nor a caller-selected destination/sender. Control Plane mail configuration does not supply this channel.

Authenticated SMTP configured before this broker was added requires an authorized tenant settings operator to save the complete settings again through the tenant UI or `PUT /tenant/smtp`, re-entering the password. Core cannot recover Keycloak's masked saved password. An SMTP test using a transient password does not populate the broker. Settings/password are tied to the current tenant realm and configuration; changed or incomplete settings can require another secure save. Never request the password in app setup or place it in manifests, examples or logs.

Missing broker credentials or incomplete configuration returns `notification_channel_unconfigured`; configuration/secret failures return `notification_channel_unavailable`. Checking `action: "channels"` exposes a safe reason code before sending. SMTP settings read needs `tenant.settings.read`; saving/testing needs `tenant.settings.update`. A saved `password_set` flag or settings `configured` response alone does not establish application-channel availability; check the service channel.

If email dispatch cannot be confirmed after it begins, Core returns HTTP 409 `notification_delivery_uncertain`; it does not automatically repeat the send. Do not retry with a fresh key or claim no email was sent. Explicit SMTP rejection returns `notification_delivery_failed`. Confirmed retries reuse the durable outcome without contacting SMTP again. Recipient mailbox receipt, when required by acceptance, must be independently observed.
