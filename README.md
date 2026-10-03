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

The current skill release is **0.7.2**; its SemVer is in `skills/galeneai-faber/SKILL.md` metadata and the snapshot lock. It covers generic SSO returns for installed tenant applications, the `authentication.login_path` manifest contract, application-completed REST password recovery, and temporary-password first sign-in with explicit challenges. Next.js/Python examples show provider discovery, reset completion, required password changes and legacy Console fallback; API/OpenAPI discovery supports Console, Control Plane and application URLs. The platform logging reference follows the platform's content rules: no personal data, user file names, search terms or query strings in logs, and route-template access lines. The schema, focused OpenAPI and source hashes are refreshed from the exact committed Core revision recorded in the snapshot lock. The skill release is independent of an app's SemVer.

It also covers manifest 1.0 application service/resource requirements, explicit service approvals and bindings, managed backend/worker credentials, durable direct operations, offline job consent, callbacks and recipient notifications. A snapshot pins source contracts and does not establish runtime deployment or delivery.

- PATCH fixes wording or tooling behavior without changing the workflow.
- MINOR adds a compatible workflow or reference.
- MAJOR changes required behavior or an assumed public contract.

When public Core contracts change, inspect the exact committed Core revision, refresh only affected snapshots and source hashes, update the lock's Core commit and skill version, and review the compatibility example. Do not copy native Core implementation into this repository. For a skill, documentation or tooling update that does not refresh Core contracts, keep the Core snapshot unchanged and bump the skill version as appropriate.

## Checks

The app-builder tooling and unit tests are stack-free. Install its small Python dependency set and run the focused suite from the repository root:

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
