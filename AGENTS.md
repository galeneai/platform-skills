# Repository Guidelines

This repository holds reusable agent skills for building Galene applications
(see `README.md`). Keep changes concise and consistent with each skill's own
wording, version policy and checks.

## Logging — mandatory principles

Every application, script or example this repository produces or describes
follows the Galene platform log format and content rules in
[`skills/galeneai-faber/references/logging.md`](skills/galeneai-faber/references/logging.md):
one JSON object per line on stdout/stderr, and logs that describe what the
software does, never whose data it handles. Never log secrets or credentials,
personal data (e-mail addresses, names, end-user IP addresses) or customer
content (prompts, model output, documents, user file names and paths, search
queries, request or response bodies), nor library output that embeds them
(URLs with query strings, `str()` of validation, database or HTTP errors). Log
opaque ids, route templates, statuses, counts and durations instead, and make
every error or warning say what failed, on which ids, with what impact and why.
The tooling in `skills/*/scripts/` follows the same rules.
