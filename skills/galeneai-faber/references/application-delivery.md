# Application delivery

Use this guide after the approved blueprint, alongside the exact public contracts in [contracts](contracts.md). It keeps the first delivery small and proves that the app works through supported tenant interfaces before broadening data coverage.

## Preflight the real prerequisites

Before implementation, confirm the target Core contract and the selected tenant can support the approved workflow. Check only what that workflow needs:

- tenant roles and endpoint permissions for sign-in, reads, writes, review, and export;
- the relevant operations and request/response schemas in the published skill snapshot and the target's public `/openapi.json`;
- the tenant's public IdP configuration and supported sign-in flow;
- required model roles, modalities, and tenant bindings;
- the documented filesystem, upload, and ingestion status APIs for source documents;
- app-scoped database resources and the app's own migration path, when persistence is required.

Use public APIs and the published snapshot; app builders do not need a Core checkout. Compare only the relevant target operations. If the public operation is missing or differs from the published contract, or a required permission, IdP setting, model binding, ingestion capability, or database prerequisite is absent, stop that dependent slice. Give the user a minimal sanitized diagnosis with the operation or capability, safe status/error code, and correlation ID when available, then refer the missing platform-side prerequisite to its responsible operator. Do not include tokens, cookies, source content, or sensitive response bodies. Do not edit the pinned snapshot or hash from app work; contract snapshot maintenance requires a verified source revision by its maintainer. This skill does not authorize changing Core or bypassing a missing contract.

## Deliver one small real workflow

Choose a representative, authorized source and complete one end-to-end user path before loading a large corpus. For a document-and-model workflow, that usually means sign-in, open or upload a document, wait for actual processing, call the tenant-bound model, persist the result, review or correct it, and export it. Use real API responses and persisted state; do not substitute static results or fixtures in the product flow. Set up each component's logging in [the platform log format](logging.md) in this first slice, including framework, server, and proxy output, and log the Core `X-Galene-Correlation-Id` returned for each call.

Select a small set of fixtures that exercise the document structures the app actually handles. For procurement documents, include examples such as dates, struck-through text, table geometry, and relevant OOXML structures before expensive inference. Inspect every page of a generated export when its deliverable has page-visual requirements. Evidence and exports should identify the real source, revision, and reviewer metadata available to the app; tie source anchors to actual source locations. Never invent page positions, reviewer identities, formatting markers, or numeric confidence for uncertain text.

Keep asynchronous work tied to the returned job identity. On refresh or navigation, recover the same job and display its actual stage and terminal state. Use documented public terminal signals; an ingestion-file completion state alone may not mean the app's larger workflow is complete. Retry and cancel must invoke the documented operation on that job; don't silently create a duplicate job. Handle authentication-required, blocked, failed, cancelled, and stale outcomes explicitly. Do not build behavior around a guessed future token or job expiry time. Distinguish fresh calls, explicitly permitted cache results, and fixtures; if acceptance requires fresh work, verify that the calls actually occurred rather than relying on a new job ID alone.

When the public write contract supports optimistic concurrency, send its expected revision. On conflict, reload the current record and show the conflict; preserve a draft only while it still belongs to that same record, and clear it when selection changes. For cursor-based lists, apply identical filters to every page, preserve the API total, and show an error rather than claiming completeness if pages, totals, or unique IDs disagree.

For model output, validate the expected structure and length. If a response is truncated, over length, or invalid, reject it with a recoverable explanation; do not silently switch model/provider, reasoning or thinking settings, or policy to force a result. When recording latency or token usage, label the actual request and observation conditions. A single run is evidence for that run, not a service-level objective.

## Verify the behavior that matters

Verify directly through the app UI and public API/configuration surfaces: permissions, source selection, loading and error states, persisted decisions after refresh, and the actual exported bytes and metadata. A browser download is verified only when the resulting file is received and can be inspected, not when the button merely appears to respond.

For webapp auth, verify configured provider visibility and ordering, credential disablement/SSO-only state, the supported SSO start/callback/exchange and rejected replay/wrong-browser state. Verify the manifest-registered login return on the installed frontend domain. For password recovery, verify the flag-false state, fixed return payload and neutral accepted confirmation. When Core advertises application completion, also verify immediate fragment removal, fixed-return completion, no automatic sign-in, password-policy retry before token expiry, and the common safe rejection for expired, replayed or cross-tenant/app tokens. Verify that a legacy target receives no unsupported `completion_mode`, or use the operator-confirmed Console fallback when reset itself is unavailable. Do not claim email delivery or completion when only the request/fixture was checked. Read [auth examples](auth-examples.md) for target prerequisites.

For credential sign-in, verify the initial username/password attempt does not request or send a TOTP. Verify the second step only when the selected target's public response explicitly signals an MFA challenge for that user; a generic 401 or tenant-wide MFA setting is not sufficient evidence. Verify `password_update_required` separately: temporary credential proof, confirmed new password, explicit TOTP challenge only when returned by the proof operation, completion into the normal BFF session, and restart rather than replay after a consumed or expired challenge. Keep all credential and challenge material out of logs and persistent browser storage. If the challenge contract or a suitable test identity is unavailable, report that behavior as unverified rather than weakening or guessing the flow.

Add focused tests for concrete risks such as tenant isolation, authorization, decision logic, persistence, or migration safety. Direct verification can be enough for simple UI or configuration changes. Prefer representative fixtures and observable behavior over tests that copy the implementation line by line. Keep one concise acceptance checklist for the approved workflow; avoid creating a second test dossier or a parallel certification record.

Prioritize first-render responsiveness and interactive critical states early, then stop when the approved acceptance result is met. After the workflow is stable, run the scoped final acceptance pass once. For a later fix, repeat only checks affected by that change. State clearly which runtime adapters were verified and which remain unverified; success on one does not prove parity on another.

## Prepare a coherent release

Group a coherent app change and verify the affected components, then keep app development separate from the platform publish/install cycle. Keep each published manifest, release note, and image digest immutable. Record complete `sha256:` image digests and the full source commit SHA as image provenance. Verify publication readiness from its actual response. Through public APIs, compare the running deployment manifest and digests with the release when the target exposes them; do not assume Docker or host access. Use the documented upgrade/update path to preserve the existing tenant installation and data; don't reinstall an existing app as a substitute for upgrade verification.

Keep these artifacts distinct in status and handoff:

- the deterministic app release bundle (manifest and release metadata);
- the component OCI images or image archive;
- the Core publication and tenant availability record;
- the running tenant deployment and its observed readiness.

A successful bundle build does not publish images, make a version available, or prove that the tenant runtime is ready. Follow [publish and install](publish-install.md) and the selected registry flow, then verify the returned immutable version/digests and the tenant-visible app behavior.
