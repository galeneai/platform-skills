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
    {"role": "files", "service": "filesystem", "operations": ["read", "write", "checkpoint"], "resource_roles": ["workspace"], "required": true, "target_components": ["backend", "worker"]},
    {"role": "processing", "service": "documents", "operations": ["extract", "ocr", "convert"], "resource_roles": ["workspace"], "target_components": ["worker"]},
    {"role": "knowledge", "service": "retrieval", "operations": ["search", "index"], "resource_roles": ["workspace"], "target_components": ["worker"]},
    {"role": "reasoning", "service": "inference", "operations": ["chat", "embedding", "transcribe"], "execution_modes": ["application", "user"], "target_components": ["backend", "worker"]},
    {"role": "research", "service": "web", "operations": ["search", "fetch", "browsing"], "resource_roles": ["workspace"], "target_components": ["worker"]},
    {"role": "compute", "service": "sandbox", "operations": ["execute"], "resource_roles": ["workspace"], "target_components": ["worker"]},
    {"role": "reports", "service": "database_connectors", "operations": ["schema.read", "query.read"], "resource_roles": ["reporting"], "target_components": ["backend"]},
    {"role": "cases", "service": "mcp", "operations": ["catalog", "invoke"], "resource_roles": ["case_tools"], "mcp_tools": ["find_case"], "execution_modes": ["user"], "target_components": ["backend"]},
    {"role": "scheduler", "service": "jobs", "operations": ["schedule"], "execution_modes": ["user"], "target_components": ["backend"]},
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

Do not send `mcp_tools` hashes in bindings. Core derives trusted pins from the approved connector/tool schemas. Do not submit the fragment using the current `install.py`, which cannot carry these fields yet. Use the verified service approval UI/API once this extension is committed and snapshotted.

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

Jobs/offline-consent and notification-send request examples are pending their actual public DTOs. Do not copy invented schedule, recipient-address, or consent fields. Their manifest roles above document intent only; finalize runnable bodies from the committed source before publishing the new snapshot.
