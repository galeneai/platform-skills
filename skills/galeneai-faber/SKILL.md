---
name: galeneai-faber
description: Build standalone apps for Galene tenants from discovery and an approved blueprint through release and tenant installation. Use for tenant application projects, not for implementing Galene platform internals.
metadata:
  version: "1.1.0"
---

# Galene.AI Faber

Build an application as an independently released tenant product that uses Galene's public app manifest and APIs. Keep the app stack-free: its local doctor, validation, packaging, and tests must not require a running Galene Compose or Kubernetes stack.

Keep tenant-user sign-in inside the webapp: do not redirect users to Keycloak's login page. Put the sign-in form on the app's own domain and send credentials through its BFF to Galene's documented public tenant-auth API. Galene remains the identity authority; the app must not implement local identity or a service account. Ask for a TOTP only after the public login or temporary-password proof explicitly signals an MFA challenge in the verified target contract; a generic 401 or tenant auth configuration is not that signal. Always load the tenant's public auth configuration: present enabled SSO connectors only through a verified return flow supported for the selected app, alongside credentials, respect credential-login disablement, complete password recovery in the app only when the target advertises that mode and its verified public contract documents the required reset operations, and handle the documented temporary-password first-sign-in flow. Preserve documented legacy recovery when the target lacks completion modes; if reset routes are absent, keep reset disabled and use only an operator-confirmed supported fallback. Follow [tenant authentication](references/tenant-authentication.md) for the exact flow and [Next.js/Python examples](references/auth-examples.md) when implementing it.

Treat the app as a standalone product under the app owner's or commissioning tenant's brand, and follow their supplied identity, colors, and design requirements. Do not present it as a Galene.ai product or add a G mark or “powered by Galene” label. When no explicit brand is supplied, use a neutral UI with a descriptive product name and no mandatory Galene platform colors. Do not impose a redesign.

## Required project decisions

For every new app, establish these two choices during discovery:

1. The target tenant and environment (for example, a named test tenant or production tenant).
2. The image registry: an owner-managed external OCI registry, or Galene's integrated registry.

Do not infer either from credentials, an existing workspace, or an earlier app. Record the choices in the project context without storing registry credentials.

## Core compatibility baseline

Every new app starts with `app.requires_core: ">=2.0,<3.0"`: it targets Galene Core 2.x and never Core 1.x. Narrow the range only when a verified feature needs a later 2.x release.

When you work on an existing app whose range excludes Core 2.x (for example the legacy `">=1.2,<2.0"` or `">=1.3,<2.0"`), or still admits 1.x, and the target platform runs Core 2.x, propose the upgrade to the user before any other change: a new app version with `requires_core: ">=2.0,<3.0"`, the app's checks repeated on Core 2.x, and a release with notes. Do not edit a published version in place and do not widen the range silently. `doctor.py` and `validate.py` print the proposal as a `WARN:`; `validate.py --target-url` fails when the target's Core version is outside the range. See [contracts](references/contracts.md#core-compatibility).

## Workflow

1. Read [discovery and blueprint](references/discovery-and-blueprint.md). Understand the business need, user, current workflow, and observable acceptance result. Produce a short blueprint and wait for the user to approve it before implementation.
2. Consult [the Galene feature map](references/platform-feature-map.md) only for features relevant to the approved app. For declared backend/worker services, read [application services](references/application-services.md) and its contract-status gate. For model-backed features, read [inference interfaces](references/inference-gateway.md): choose tenant-user REST, application durable operations or backend live channels, and verify the required roles and native availability. Choose public app contracts and tenant capabilities; do not add native Galene code or rely on internal database access. For individual tenant sign-in, user-delegated API calls, or agent/session participation, also read [tenant authentication](references/tenant-authentication.md).
3. Before writing a manifest, using app APIs, or packaging a release, read [contracts and snapshots](references/contracts.md). Treat the pinned snapshot as the contract at its recorded Platform Core commit, not a released/deployed version. When only a tenant Console, Control Plane or application URL is available, read [API discovery](references/api-discovery.md) to resolve the public Core API base and fetch that target's OpenAPI JSON; do not guess API hosts. Keep manifest 1.0 and choose `app.requires_core` from verified release compatibility, not a universal range copied from an example. Faber verifies qualified target versions and the declared service/model schemas and HTTP routes before mutations; native feature flags, WebSocket protocols, grants and runtime readiness require separate checks. Older Core revisions may ignore fields and compatibility constraints. A version range, advertised route or successful installation alone does not establish feature support. Core remains authoritative at validation/publication.
4. After blueprint approval, read [application delivery](references/application-delivery.md). Preflight the public contracts and tenant prerequisites, then build the smallest real user workflow end to end. Make every component log in [the platform log format](references/logging.md) from the first slice. Verify the behavior and its concrete risks; avoid tests that only duplicate implementation details. Ask for a new approval only when a requirement must expand beyond the approved blueprint.
5. Read [runtime readiness](references/runtime-readiness.md) before writing the container, proxy, health endpoints, database access, configuration or volumes. Read [security and release](references/security-release.md) before declaring capabilities, database resources, secrets, or release versions. If integrated registry was selected, also read [integrated registry status](references/integrated-registry.md); do not promise multi-component atomic import until its final API is in a committed snapshot.
6. Use the stack-free tools described in [tooling](references/tooling.md), then follow [publish, availability, and install](references/publish-install.md) to release and install the app. Verify the tenant-visible deployment state when that action is in scope.

## Non-negotiable boundaries

- Keep app source and images outside Platform Core. Do not add Galene-native code, platform migrations, plugins, or hooks to the app release.
- Use only documented public app and tenant APIs. Do not assume access to a Core checkout, source tree, database, host, or operator credentials. If a required contract or tenant prerequisite is missing, stop at the smallest sanitized diagnosis and hand it to the responsible platform operator; this skill never authorizes a Core change or a private workaround.
- Keep Core-managed component bootstrap/access tokens server-side. Application service grants and verified user delegation are separate authority; offline work additionally needs the explicit consent contract.
- Never put passwords, access tokens, private keys, registry auth files, tenant secrets, or live tenant data in the skill, manifest, archive, tests, logs, or generated docs. Use the tenant's secret-entry flow and server-side secret references.
- App-owned database migrations run from the app at startup against its runtime DATABASE_URL. Do not ask Core or the runtime adapter to run application migration hooks.
- Keep app behavior and contracts equivalent on Elettra/Docker Compose and Arethusa/Kubernetes. A single-runtime check does not establish parity: a Compose run does not exercise the injected database URL, the service-mesh sidecar, platform-injected component URLs or storage classes. Follow [runtime readiness](references/runtime-readiness.md) and verify on a Kubernetes target before claiming it.
- Use the documented, authenticated Control Plane application API or UI for publisher installation, or the documented tenant API/UI when the user chooses tenant-scoped installation. Keep the target tenant explicit in either flow; do not access platform internals or bypass tenant authorization.

## Progressive references

- Start with [discovery and blueprint](references/discovery-and-blueprint.md) for each project.
- Read [application delivery](references/application-delivery.md) after blueprint approval for preflight, the first end-to-end slice, targeted verification, and release readiness.
- Read [the Galene feature map](references/platform-feature-map.md) when choosing Core, models, ingestion, browsing, sandbox, knowledge-base, or connector integration.
- Read [inference interfaces](references/inference-gateway.md) when choosing or calling models, tools, structured output, embeddings, speech, SystemOne, realtime or token counting; it separates tenant-user REST, durable application operations and backend live channels.
- Read [application services](references/application-services.md) for manifest 1.0 service/resource requirements, explicit installation approvals, managed component tokens, user delegation, and durable operations; use its [examples](references/application-services-examples.md) only after the recorded snapshot gate is met.
- Read [installed application MCP](references/installed-application-mcp.md) when suggesting or implementing app-owned tools for other apps or specialized agents, including explicit revocable owner consent and offline execution.
- Read [jobs, callbacks and notifications](references/application-jobs-notifications.md) for offline consent, signed callback receivers, recipient inbox/preferences, and tenant SMTP broker prerequisites.
- Read [tenant authentication](references/tenant-authentication.md) when an app authenticates tenant users, calls Core as a user, or participates in agent/session execution.
- Read [platform log format](references/logging.md) when writing a component's logging setup, Dockerfile, or proxy configuration.
- Read [API discovery](references/api-discovery.md) when resolving the Core API/OpenAPI from a Console, Control Plane or application URL.
- Read [Next.js/Python auth examples](references/auth-examples.md) when building a webapp sign-in, SSO callback or password-recovery entry point.
- Read [contracts and snapshots](references/contracts.md) when shaping a manifest or calling a published app API.
- Read [runtime readiness](references/runtime-readiness.md) when writing the Dockerfile, web proxy, health endpoints, database connection, configuration derivation, volumes or first-start data, and before claiming Kubernetes support.
- Read [security and release](references/security-release.md) when an app handles tenant data, capabilities, app databases, registry images, or installation.
- Read [integrated registry status](references/integrated-registry.md) only if integrated registry import is selected or discussed.
- Read [publish, availability, and install](references/publish-install.md) when publishing a version or installing it into a tenant.
- Read [tooling](references/tooling.md) when using this skill's doctor, validate, package, or install scripts.
