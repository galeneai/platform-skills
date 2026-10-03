# Application service examples

These fictional examples accompany the [source preview](application-services.md#contract-status). They are **not** covered by the current packaged contract lock. Do not run publication/install from them until the final Core snapshot and target prerequisites are verified. UUIDs and image digests are placeholders; no token values belong here.

## Manifest additions

Merge these fields into an ordinary manifest with named `backend` and `worker` components of the corresponding kinds. They remain schema version 1.0. Select only roles needed by the approved blueprint; this example illustrates choices, not a recommended blanket grant.

```json
{
  "schema_version": "1.0",
  "resource_requirements": [
    {"role": "workspace", "kind": "filesystem", "access": "read_write", "required": true},
    {"role": "reporting", "kind": "db_connector", "required": false},
    {"role": "case_tools", "kind": "mcp_connector", "required": false},
    {"role": "reviewer", "kind": "notification_recipient", "required": false}
  ],
  "service_requirements": [
    {"role": "files", "service": "filesystem", "operations": ["read", "write", "checkpoint"], "resource_roles": ["workspace"], "execution_modes": ["application", "user"], "required": true, "target_components": ["backend", "worker"]},
    {"role": "processing", "service": "documents", "operations": ["extract", "ocr", "convert"], "resource_roles": ["workspace"], "target_components": ["worker"]},
    {"role": "knowledge", "service": "retrieval", "operations": ["search", "index"], "resource_roles": ["workspace"], "target_components": ["worker"]},
    {"role": "reasoning", "service": "inference", "operations": ["chat", "embedding", "transcribe"], "execution_modes": ["application", "user"], "target_components": ["backend", "worker"]},
    {"role": "research", "service": "web", "operations": ["search", "fetch", "browsing"], "resource_roles": ["workspace"], "target_components": ["worker"]},
    {"role": "compute", "service": "sandbox", "operations": ["execute"], "resource_roles": ["workspace"], "target_components": ["worker"]},
    {"role": "reports", "service": "database_connectors", "operations": ["schema.read", "query.read"], "resource_roles": ["reporting"], "target_components": ["backend"]},
    {"role": "cases", "service": "mcp", "operations": ["catalog", "invoke"], "resource_roles": ["case_tools"], "mcp_tools": ["find_case"], "execution_modes": ["user"], "target_components": ["backend"]},
    {"role": "scheduler", "service": "jobs", "operations": ["schedule"], "execution_modes": ["application", "user"], "target_components": ["backend"]},
    {"role": "alerts", "service": "notifications", "operations": ["send"], "resource_roles": ["reviewer"], "target_components": ["worker"]}
  ],
  "model_requirements": [
    {"role": "writer", "slot": "llm", "capabilities": ["chat"], "input_modalities": ["text"]},
    {"role": "vision", "slot": "llm", "capabilities": ["chat"], "input_modalities": ["text", "image"]},
    {"role": "vectors", "slot": "embedding", "capabilities": ["embedding"], "input_modalities": ["text"]},
    {"role": "audio", "slot": "stt", "capabilities": ["transcription"], "input_modalities": ["audio"]}
  ]
}
```

Do not declare the generated service token/deployment/context env variables in either component's `env_schema`. Model bindings are selected through the installation model-role controls; declaring a model role does not approve inference service access.

## Installation selection

This is a fragment of a deployment request, alongside its package/version and other configuration. `files` is the required service. Optional roles have no approval until selected. The resource IDs must come from the authorized target tenant catalog.

```json
{
  "approved_services": ["files", "reasoning", "reports", "cases"],
  "service_bindings": {
    "workspace": {"resource_id": "00000000-0000-4000-8000-000000000101", "access": "read_write"},
    "reporting": {"resource_id": "00000000-0000-4000-8000-000000000102", "access": "read"},
    "case_tools": {"resource_id": "00000000-0000-4000-8000-000000000103", "access": "read"}
  }
}
```

Do not send `mcp_tools` hashes in bindings. Core derives trusted pins from the approved connector/tool schemas. Once the extension is committed and snapshotted, pass repeated `--approved-service` options for the selected roles and a `--service-bindings` file containing only the inner resource-role mapping shown above. See [tooling](tooling.md#explicit-service-selections-at-installation), or use the verified approval UI/API.

## Operation bodies

Each body goes to `POST /v1/services/operations` with the app access bearer. For user-mode `cases`, also supply the actual user's delegated bearer header. Send a persisted `Idempotency-Key` of 1–200 non-space printable ASCII characters. The response is the direct operation DTO with HTTP 202; retry the identical body/key only under the same grant revision. These examples illustrate argument shapes read from the current adapters; final snapshot verification is still required.

```json
{"service_role":"research","operation":"search","arguments":{"query":"public annual report","limit":5}}
```

```json
{"service_role":"research","operation":"fetch","arguments":{"url":"https://example.com/report"}}
```

```json
{"service_role":"research","operation":"browsing","arguments":{"action":"open","url":"https://example.com"}}
```

Use the returned `context_id` for subsequent deterministic browsing actions, including `close`. A browser download also supplies `filesystem_role` and a relative `path`; the selected role must grant write access.

```json
{"service_role":"compute","operation":"execute","arguments":{"filesystem_role":"workspace","command":"python --version","cwd":"/workspace","timeout_seconds":30}}
```

```json
{"service_role":"reports","operation":"schema.read","arguments":{"resource_role":"reporting"}}
```

```json
{"service_role":"reports","operation":"query.read","arguments":{"resource_role":"reporting","sql":"SELECT case_id, status FROM cases WHERE status = :status","parameters":{"status":"open"},"max_rows":100}}
```

```json
{"service_role":"processing","operation":"extract","arguments":{"resource_role":"workspace","path":"source/report.pdf"}}
```

```json
{"service_role":"processing","operation":"ocr","arguments":{"resource_role":"workspace","path":"source/scan.pdf","vision_role":"vision"}}
```

```json
{"service_role":"processing","operation":"convert","arguments":{"resource_role":"workspace","path":"source/report.docx","target":"pdf","target_resource_role":"workspace","output_path":"exports/report.pdf"}}
```

Extraction/OCR/indexing creates or updates tracked processing metadata and needs writable source authority. Conversion uses a new destination path. Poll the public operation until downstream completion is known; do not infer readiness from ingestion acceptance.

```json
{"service_role":"knowledge","operation":"index","arguments":{"resource_role":"workspace","path":"source/report.pdf","mode":"vector"}}
```

```json
{"service_role":"knowledge","operation":"search","arguments":{"resource_roles":["workspace"],"query":"What was approved?","mode":"vector","top_k":8}}
```

```json
{"service_role":"reasoning","operation":"chat","arguments":{"model_role":"writer","messages":[{"role":"user","content":"Summarize this approved text."}],"max_tokens":512}}
```

```json
{"service_role":"reasoning","operation":"embedding","arguments":{"model_role":"vectors","input":["approved text"]}}
```

For `transcribe`, use `{model_role:"audio", audio_base64:<actual audio bytes encoded as base64>, filename:"recording.wav", content_type:"audio/wav"}`; `language`, `prompt`, and `temperature` are optional. This is a shape description, not a valid audio fixture. Keep recordings out of diagnostic logs.

```json
{"service_role":"files","operation":"read","arguments":{"resource_role":"workspace","path":"exports/report.pdf"}}
```

```json
{"service_role":"files","operation":"write","arguments":{"resource_role":"workspace","path":"notes/approved.txt","content_base64":"YXBwcm92ZWQ="}}
```

```json
{"service_role":"files","operation":"checkpoint","arguments":{"resource_role":"workspace","label":"Before review"}}
```

```json
{"service_role":"cases","operation":"catalog","arguments":{"resource_role":"case_tools"}}
```

```json
{"service_role":"cases","operation":"invoke","arguments":{"resource_role":"case_tools","tool":"find_case","arguments":{"case_id":"demo-case"}}}
```

The inner MCP tool arguments must match that exact approved remote tool's current schema; the example field is fictional. A catalog result does not grant another tool.

## Schedule and offline consent

Approve `scheduler` and its target `files` role, with `workspace` bound writable. This source-backed shape follows the probe's scheduled filesystem write, using the logical roles in this guide. Choose a future `dtstart` when using it; these fixed dates are fictional examples. The offset-free anchor uses the explicit calendar timezone.

```json
{
  "service_role": "scheduler",
  "operation": "schedule",
  "arguments": {
    "action": "create",
    "name": "Approved report export",
    "service_role": "files",
    "operation": "write",
    "arguments": {"resource_role": "workspace", "path": "exports/scheduled.txt", "content_base64": "YXBwcm92ZWQ="},
    "calendar": {"timezone": "Europe/Rome", "dtstart": "2026-10-04T09:00:00", "rrules": ["FREQ=DAILY;COUNT=1"], "rdates": [], "exdates": []},
    "overlap_policy": "buffer_one",
    "misfire_policy": "coalesce",
    "callback": {"url": "https://app.example.com/api/job-events", "events": ["job.operation.completed", "job.operation.failed"]}
  }
}
```

For application-mode work, submit with only the app bearer. For user-mode work, both `scheduler` and `files` must allow user execution; include the actual creator's delegated bearer. The completed create operation returns `result.job_id`; user mode returns job status `pending_consent`.

For user approval, GET `/application-jobs/{job_id}` with that creator's ordinary tenant bearer, present the returned immutable work/calendar/scope, and POST `/application-jobs/{job_id}/approve` only after their explicit decision. The JSON shape is `{expires_at: <timezone-aware future timestamp within 1 minute–30 days>, scope: <complete scope copied from GET>}`. A role-only scope fragment is not sufficient. This user call does not use the app bearer or delegation header. Revoke with POST `/application-jobs/{job_id}/revoke`.

Use these operation arguments to manage the job; every separate action has its own persisted outer operation key:

```json
{"service_role":"scheduler","operation":"schedule","arguments":{"action":"get","job_id":"00000000-0000-4000-8000-000000000201"}}
```

Replace `get` with `pause`, `resume`, `delete` or `run` when intended. Poll `active_occurrence.operation_id` or `last_result.operation_id` to verify the target operation; confirm the resulting file bytes separately when acceptance requires them. The probe distinguishes outer run success, target completion, file readback and verified callback receipt.

## Signed callback receiver

The probe stores each job's returned verification key and deduplicates stable event IDs with a payload fingerprint. This minimal verification function uses the exact received raw bytes; add bounded body parsing, known-job lookup and durable deduplication before returning 2xx. It is an app example, not a new Faber runtime dependency.

```python
import base64
import json
import time
from uuid import UUID
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def verify_job_event(raw, headers, verification_key):
    # headers must support case-insensitive HTTP header lookup.
    if len(raw) > 16_384:
        raise ValueError("Event too large")
    event = json.loads(raw)
    event_id = headers["X-Galene-Event-Id"]
    timestamp = headers["X-Galene-Event-Timestamp"]
    if headers["X-Galene-Signature-Algorithm"] != "Ed25519":
        raise ValueError("Invalid algorithm")
    for field in ("event_id", "job_id", "operation_id"):
        UUID(event[field])
    if event["event_id"] != event_id or abs(int(timestamp) - time.time()) > 300:
        raise ValueError("Invalid identity or timestamp")
    expected = {"job.operation.completed": {"succeeded"},
                "job.operation.failed": {"failed", "cancelled"}}
    if event["status"] not in expected.get(event["event"], set()):
        raise ValueError("Invalid event status")
    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(verification_key, validate=True))
    signature = base64.b64decode(headers["X-Galene-Event-Signature"], validate=True)
    key.verify(signature, f"{event_id}.{timestamp}.".encode() + raw)
    return event
```

Resolve `verification_key` only from the authenticated job record stored for `event.job_id`; never trust a key supplied by the callback. Treat exceptions as rejected delivery. Persist the event ID and payload fingerprint with the resulting app change; a verified duplicate with the same fingerprint returns 2xx without repeating the effect, while a changed payload is rejected.

## Notification and recipient receipt

Approve `alerts`, bind `reviewer` to the authorized recipient and keep that user's preferences enabled. Inspect the channel without requesting any SMTP credential:

```json
{"service_role":"alerts","operation":"send","arguments":{"action":"channels"}}
```

```json
{"service_role":"alerts","operation":"send","arguments":{"channel":"internal","recipient_roles":["reviewer"],"title":"Report ready","body":"The approved export is available."}}
```

For email, use the same send shape with `channel: "email"` and a **new** operation key only when intentionally creating a distinct notification. The channel must be configured through the tenant SMTP broker; authenticated preexisting SMTP needs a password re-save through the authorized tenant settings UI/API. Never send an address/password in this body. User-mode send requires a user-enabled manifest role and the bound recipient to be that same user.

Use the recipient's ordinary tenant bearer for GET `/application-notifications?limit=100`. Match `result.deliveries[].delivery_id` from the sender operation to inbox `notifications[].notification_id` and the sender operation's `id` to inbox `operation_id`. POST `/application-notifications/{notification_id}/read` marks only that recipient's record read. This matches the probe's receipt verification rather than treating a sender result as proof of recipient visibility.

GET `/application-notifications/preferences/{deployment_id}` reads recipient preferences; PUT the same route with this complete body to disable email while retaining internal delivery:

```json
{"internal_enabled":true,"email_enabled":false}
```

Email status `sent` confirms SMTP submission, not mailbox delivery. `notification_delivery_uncertain` must not trigger a fresh-key resend. See [jobs, callbacks and notifications](application-jobs-notifications.md) for permissions, current authority checks and exact lifecycle/error distinctions.
