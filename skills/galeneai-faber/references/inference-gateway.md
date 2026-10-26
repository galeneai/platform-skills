# Inference interfaces

Read this when choosing or implementing model-backed app features. The [snapshot](contracts.md) pins the Core source contract, not a deployed release or a model certification. All interfaces below are on the **public Core API**, discovered through [API discovery](api-discovery.md). The private Rust gateway, `/config`, its `/v1/embed` route, health/readiness probes and gateway/provider keys are operator internals, never app integration surfaces.

## Choose the interface and authority

Use tenant-user REST for user-authenticated chat/Responses features. Use approved application services for backend/worker work under installed component authority. Choose durable operations for a persisted single result; choose live channels for speech or realtime. Do not send an application service bearer to ordinary tenant endpoints or manufacture a user/session to obtain inference. Shared token exchange, grants, delegation and durable lifecycle rules stay in [application services](application-services.md).

### Tenant-user REST

The BFF uses the signed-in user's supported tenant bearer and the endpoint's permission; [tenant authentication](tenant-authentication.md) owns sign-in and token storage.

| Interface | Purpose and permission |
|---|---|
| `GET /models/catalog` | Capability-aware selection: roles/defaults, modalities, context, reasoning controls and active embedding spaces; `model.list`. |
| `GET /v1/models`, `GET /v1/models/native` | Canonical model IDs or native model/default projection; `model.list`. A listed ID is not proof every operation is ready. |
| `POST /v1/chat/completions` | Stateless OpenAI-compatible chat, tools, JSON output and optional SSE; `inference.chat.create`. |
| `POST /v1/chat`, `POST /v1/chat/stream` | Stateless camelCase native chat and named SSE; `inference.chat.create`. These public Core routes are not direct gateway access. |
| `POST /v1/embeddings` | Text/image vectors for an assigned embedding model; `inference.embedding.create`. |
| `POST /v1/responses` | Stateless Responses input, or an owned session through `conversation`; `response.create`. |
| `POST /v1/responses/count_tokens` | Input counting without generation; `response.tokens.count`. |
| `DELETE /v1/responses/{response_id}` | Asynchronous cancellation of an active owned session-bound response, with its conversation in the body; `response.create`. Not stateless cancellation. |
| `POST /v1/audio/transcriptions` | Multipart uploaded audio under the assigned STT model; `inference.chat.create`. |
| `POST /v1/audio/speech` | TTS audio bytes or native speech SSE; `inference.chat.create`. |
| `POST /v1/systemone` | Typed state/question decisions; `inference.chat.create`. |
| `POST /v1/ocr`, `GET /v1/ocr/{attachment_id}`, `POST /v1/ocr/{attachment_id}/retry` | Document OCR lifecycle; `response.create`, plus current document/filesystem authority. |
| `POST /v1/videos/captions` | Bounded video captioning through Responses; `response.create`. |

Send the full history for stateless chat; `sessionId` on native chat and `metadata.session_id` on Chat Completions are rejected. Native image parts use base64 bytes plus `mimeType`; Chat Completions uses inline `image_url` data URLs, not remote image URLs. Use each route's schema rather than translating field casing by guesswork.

Chat Completions supports `tool_choice` `none`, `auto`, `required` and a named declared function. Responses supports `auto`/`none`; forced/named choices are rejected. Client function calls require the app's own authorization, argument validation and execution; a model tool call grants no authority. Responses can execute `file_search` against owned vector stores with `vector_store.search`; stateless file search cannot be combined with client function tools unless tools are disabled. With `conversation`, Core runs the owned session's agent loop and tools; session creation/access is a separate contract.

Use Chat Completions `response_format` or stateless Responses `text.format` for `json_object`/`json_schema`. JSON schemas are bounded to 64 KiB and 64 nesting levels. Unsupported provider enforcement returns `STRUCTURED_OUTPUT_UNSUPPORTED`; never silently replace structured output with a prompt-only promise. Responses JSON formatting is rejected with `conversation`. Native chat does not expose the same top-level format field. Validate the returned JSON and completion state in the app.

Choose reasoning from the resolved catalog's `reasoning_efforts` and `thinking_control`. Native fields are `reasoning`, `reasoningEffort`, `thinkingBudgetTokens`, `providerParams`; Chat Completions uses `enable_thinking`, `reasoning_effort`, `thinking_budget_tokens`, `provider_params`. Responses has its own `reasoning` object. Do not assume a supported effort from a model/provider name, combine contradictory overrides or use provider parameters to supply credentials, endpoints or platform authority. `strict_mode`/`strictMode` is not a returned diagnostic or proof that the provider honored every parameter.

Embeddings accept the selected model's text/image input shapes and `encoding_format` `float` or base64 little-endian float32. `dimensions` must equal the model's indexed size; it is not an app-selected arbitrary reduction. Core owns the active embedding space and migration/indexed dimensions; durable application embeddings remain text-only.

### Application durable operations

Submit `POST /v1/services/operations` with `{service_role, operation, arguments}`, the short application bearer and persisted `Idempotency-Key`. Poll `GET /v1/services/operations/{operation_id}`. HTTP 202 is acceptance; use the actual terminal state and result. Keep optional verified user delegation on submission, polling, cancellation and artifact reads.

| Operation | `arguments` and selected model slot |
|---|---|
| `chat` | `model_role`, bounded text `messages`, optional `max_tokens`, `temperature`, `disable_reasoning_if_supported`; `llm`. No tools, structured-output field or token stream in this adapter. |
| `embedding` | `model_role`, text `input` (up to 128 nonempty texts); `embedding`. |
| `transcribe` | `model_role`, `audio_base64`, `filename`, `content_type`, optional `language`, `prompt`, `temperature`; `stt`. |
| `decide` | `model_role`, `state`, `questions`, optional native decision fields from the source-pinned contract; `classification`. Never supply `model` instead of the role. |

`speak` and `realtime` are approved inference operation names, but **do not submit them to the durable operation endpoint**: its adapter rejects them. Use the live channels below. Durable inference result accounting identifies the actual resolved model and operation. Unknown/unreported usage remains unknown, not an invented zero.

### Application live channels

| Interface | Selection |
|---|---|
| `POST /v1/services/inference/{service_role}/speak` | Approved `speak` service role; JSON body uses `model_role` and speech options, not `model`; bound `tts` slot. |
| `WS /v1/services/inference/{service_role}/realtime?model_role=...&mode=...` | Approved `realtime` service role and bound realtime model role. |

Open these from the app backend with its short application bearer. When user mode is approved, include the actual user's bearer in `X-Galene-User-Authorization`. Browser-originated channels are refused; there is no browser ticket or query-token authentication. The browser talks to the app's own authenticated BFF channel; Core credentials remain server-side.

Speech supports `response_format` (`mp3`, `opus`, `aac`, `flac`, `wav`, `pcm`), `stream`, `stream_format` (`audio`/`sse`) and model-native options such as voice, instructions, reference audio and word timestamps. Use only options supported by the bound model; do not invent a voice or silently change its format. `extra_params` is bounded and cannot override inference authority. Word timestamps and audio are customer content, never diagnostic log fields.

### Tenant-user realtime

`WS /v1/realtime?model=...&mode=...` uses backend-held tenant-user authorization and `inference.chat.create`, not an application bearer. It also refuses browser origins and query-string credentials. The same protocol and runtime gates below apply.

## Realtime protocol and completion

WebSockets are absent from OpenAPI. The source pin additionally covers Core's public realtime routers/relay and the Rust media protocol; obtain the target's supported public protocol from its operator and verify the channel before enabling it. HTTP schema presence or the `realtime` enum alone is not WebSocket support.

- `mode=turn_based` is the default native transcription protocol; its captured request PCM is 16 kHz. `mode=duplex` selects the upstream native duplex protocol; captured request PCM is 24 kHz. Use the model's documented formats/events, not an assumed universal audio-chat protocol.
- Duplex starts with `session.update` (or a permitted `session.resume`) and requires a `session.created`/`session.resumed` event with negotiated capabilities before data. Check those capabilities before interruption, binary audio or resumption; not every realtime model supports all of them.
- Resume only the returned native `session_id`, through the same selected model/channel with `session_id` in the reconnect query. Lost affinity is not a fresh session: surface it rather than replaying customer audio. A native session handle is not a Core agent conversation or an access grant.
- Core consumes `{"type":"galene.session.renew","authorization":"Bearer ..."}` and acknowledges `galene.session.renewed`. Application user mode also supplies `user_authorization` when renewing that delegation. Renew only from the backend; the verified tenant/component/user/grant identity cannot change. Never log these events. Renewal does not recover revoked grants or switch actors.
- Long channels revalidate model, grants, tenant/license and capacity every 30 seconds. Revocation, expired delegation or model changes can terminate them. Handle policy closure (1008) and transport failure (1011), and close the app relay on browser disconnect; do not leak upstream work or auto-replay an uncertain effect.

Successful Chat Completions SSE ends with a usage/final chunk and `[DONE]`; a failure after streaming starts can end without `[DONE]`. Native chat sends `meta`, text/thinking/tool deltas and `done` or `error`; Responses sends named events ending in `response.completed`, `response.incomplete` or `response.error`. Speech may be native bytes or `speech.audio.*` events according to Content-Type. A socket close, EOF, HTTP 200 or queued operation does not prove a complete answer, completed audio generation or playback. Preserve cancellation, failure, truncation and partial results explicitly.

## Token counts are scoped observations

`POST /v1/responses/count_tokens` accepts a tenant-authorized model, text/Responses input, optional instructions and function tools; image inputs are rejected. Inspect `count_scope`, `count_source`, `is_exact` and `max_model_len` alongside `input_tokens`/`total_tokens`.

Provider-native OpenAI, supported Anthropic Messages and Google Generative AI counting can report `count_scope: "response"`, `is_exact: true`, including the supported complete request. Unsupported input translations or unavailable counters fall back to `count_scope: "text"`, `is_exact: false`: extracted input plus separately counted instructions, excluding framing and tools. For registered vLLM models Core uses that model server's `/tokenize` (not `/v1/tokenize`); even a real tokenizer count is text-only here. Local `tiktoken` or a pessimistic UTF-8-byte estimate may be used instead. Apps call Core, never the model server or tokenizer directly. A text count is neither an exact final prompt count nor a guarantee that generation fits; budget output and framing separately. Counting is not generation usage or a billing quote.

## Declare requirements and verify availability

| Model slot | Required capability | Base input modality |
|---|---|---|
| `llm` | `chat` | `text` |
| `embedding` | `embedding` | `text` |
| `stt` | `transcription` | `audio` |
| `tts` | `tts` | `text` |
| `classification` | `systemone` | `text` |
| `realtime` | `realtime` | `audio` |

Declare only required roles, adding `function_calling` and image/audio modalities where needed and actually supported. `min_context_window` is optional and only valid for `llm`; a missing registry window is not proof of the minimum. Installation approvals and model bindings are separate; one physical model may supply multiple roles but does not acquire independent capacity per role. Reflect optional/unready roles in feature state instead of choosing an arbitrary fallback.

SystemOne takes `state` and an ordered question map with `choice`, `noul` or `score` types. Preserve typed answers, native probabilities, confidence and diagnostics (`label_mass`, `argmax_is_label`); do not manufacture them from a chat answer or treat them as a calibrated business guarantee. Generic classification, chat JSON or a compatible checkpoint name does not establish the `systemone` operation.

Before enabling native speech, SystemOne or realtime, verify the target's compatible Rust gateway and operator-enabled `INFERENCE_GATEWAY_MULTIMODAL_ENABLED` (false by default), current service/user permissions, bound model capabilities and successful native operation readiness. Disabled routes can return 404 despite being advertised in OpenAPI. The flag is operator configuration, not an app env setting. Ordinary transcription can use the legacy dispatch when that flag is false. Duplex additionally needs the supported native plugin/deployment and negotiated capabilities. Native watermark qualification is unavailable; required tenant watermark policy can make these operations unavailable. Do not relax tenant policy to obtain a result.

Use a verified build/release constraint in `app.requires_core`, never a guessed minimum inferred from this develop pin. The tooling's stable-version/schema check cannot prove feature-flag enablement, WebSocket behavior, provider quality, GPU capacity or runtime parity. Handle 429/503 with the documented `Retry-After`; a model-not-ready error is not permission to switch providers or raise quotas. Core owns provider configuration, accounting and encrypted governance capture, including audio. Capture completion is not playback; keep prompts, output, recordings, reference audio, timestamps and tokens out of app logs. Follow [logging](logging.md).

Verify one representative workflow and its directly relevant denial/revocation/disconnect case on each claimed runtime. Stack-free tests and a catalog/source snapshot do not certify a live provider, audio quality or a deployment.
