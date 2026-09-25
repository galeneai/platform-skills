# Platform skills

This repository contains reusable Codex skills for work on Galene applications and platform workflows. The app-builder skill lives at [skills/galeneai-app-builder](skills/galeneai-app-builder/); it guides an application from discovery and approved blueprint through a portable release and tenant installation.

## Install the skill in Codex

Copy the skill directory into the user skill directory:

```sh
mkdir -p ~/.codex/skills/galeneai-app-builder
cp -R skills/galeneai-app-builder/. ~/.codex/skills/galeneai-app-builder/
```

After installation, start a new Codex task and invoke it with `$galeneai-app-builder`. For development, when the destination path does not exist, a symlink from `~/.codex/skills/galeneai-app-builder` to this checkout lets Codex load local edits. No plugin or platform runtime is required.

## Version and update policy

The current skill release is **0.2.0**; its SemVer is in `skills/galeneai-app-builder/SKILL.md` metadata. It is independent of an app's SemVer and the Platform Core commit. The contract baseline and exported schema/OpenAPI SHA-256 values are in [snapshot-lock.json](skills/galeneai-app-builder/references/contracts/snapshot-lock.json).

- PATCH fixes wording or tooling behavior without changing the workflow.
- MINOR adds a compatible workflow or reference.
- MAJOR changes required behavior or an assumed public contract.

When public Core contracts change, inspect the exact committed Core revision, refresh only affected snapshots and source hashes, update the lock's Core commit and skill version, and review the compatibility example. Do not copy native Core implementation into this repository. For a docs-only update, keep the Core snapshot unchanged and bump the skill version as appropriate.

## Checks

The app-builder tooling and unit tests are stack-free. Install its small Python dependency set and run the focused suite from the repository root:

```sh
python3 -m pip install -r skills/galeneai-app-builder/scripts/requirements.txt
python3 -m unittest discover -s skills/galeneai-app-builder/tests -v
```

These checks do not validate deployment behavior; app projects must verify the relevant behavior on each supported Compose and Kubernetes adapter.
