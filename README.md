# Platform skills

This repository contains reusable Codex skills for work on Galene applications and platform workflows. [Galene.AI Faber](skills/galeneai-faber/) guides an application from discovery and approved blueprint through a portable release and tenant installation.

## Install the skill in Codex

Copy the skill directory into the user skill directory:

```sh
mkdir -p ~/.codex/skills/galeneai-faber
cp -R skills/galeneai-faber/. ~/.codex/skills/galeneai-faber/
```

After installation, start a new Codex task and invoke it with `$galeneai-faber`. For development, when the destination path does not exist, a symlink from `~/.codex/skills/galeneai-faber` to this checkout lets Codex load local edits. No plugin or platform runtime is required.

## Version and update policy

The current skill version is **1.0.0**; its SemVer is in `skills/galeneai-faber/SKILL.md` metadata and the snapshot lock. This major update refreshes the authoring baseline to Platform Core develop commit `a44fd195ea92e3387b5e7a003b79b061e95501b3` and adds [inference interface guidance](skills/galeneai-faber/references/inference-gateway.md): tenant-user REST, durable application operations and backend live audio/realtime channels. It covers all six model slots, tools/structured output/reasoning, multimodal embeddings, SystemOne decisions, speech/transcription, token-count scope and native runtime gates. The offline export honestly retains Core's `0.0.0+dev` identity; a source pin is not a released or deployed version. Preflight qualifies stable Core 1.3+ in major 1 or stable 2.x with the required contracts, checks declared model/inference features and rejects unknown/development/prerelease/future-major targets. Core still validates the full release constraint. WebSocket support and native readiness require separate verification.

Existing conditional guidance for generic app SSO returns, `authentication.login_path` and application-completed password recovery is retained; those contracts remain absent from this pinned baseline and require separate target verification. Temporary-password first sign-in uses the explicit challenge contract. Next.js/Python examples cover provider discovery, conditional recovery and required password changes; API discovery supports Console, Control Plane and application URLs. Logging follows the platform content rules. The schema, focused OpenAPI and source hashes come from the exact revision recorded in the lock. The skill version is independent of app and Core versions.

It also covers manifest 1.0 application service/resource requirements and internal MCP/callback endpoints, explicit service approvals and bindings, managed backend/worker credentials, durable direct operations, offline job consent, callbacks and recipient notifications. The focused snapshot includes installed MCP registration, agent tool binding, explicit revocable offline owner consent and provider introspection. A snapshot pins source contracts and does not establish runtime deployment or delivery.

Version 0.8.0 adds a runtime-readiness guide (injected libpq-style database URL, service-mesh proxy and probe behaviour, derived configuration, persistent volumes, zero-touch demo apps and Kubernetes verification) and non-blocking manifest warnings in `validate.py`.

- PATCH fixes wording or tooling behavior without changing the workflow.
- MINOR adds a compatible workflow or reference.
- MAJOR changes required behavior or an assumed public contract.

When public Core contracts change, inspect the exact committed Core revision, refresh only affected snapshots and source hashes, update the lock's Core commit and skill version, and review the compatibility example. Do not copy native Core implementation into this repository. For a skill, documentation or tooling update that does not refresh Core contracts, keep the Core snapshot unchanged and bump the skill version as appropriate.

## Checks

The app-builder tooling and unit tests are stack-free and require Python 3.10+. Install its small Python dependency set and run the focused suite from the repository root:

```sh
python3 -m pip install -r skills/galeneai-faber/scripts/requirements.txt
python3 -m unittest discover -s skills/galeneai-faber/tests -v
```

The auth example has separate checks using the app's FastAPI/httpx dependencies:

```sh
python3 -m unittest discover -s skills/galeneai-faber/assets/auth/python -v
```

The Next.js page can be type-checked in an app with React/TypeScript. See [auth integration examples](skills/galeneai-faber/references/auth-examples.md) for the required session/store adapters and target SSO/recovery limitations.

These checks do not validate deployment behavior; app projects must verify the relevant behavior on each supported Compose and Kubernetes adapter.
