# Expose an installed application as MCP

Suggest this integration when specialized agents or other applications should use
the app's own business actions. The app implements the MCP tools and its business
authorization. Core registers the installed destination, authenticates the caller
and routes the request. A manifest declaration alone grants no caller access.

Use this reference only with the pinned installed-endpoint and owner-consent
contract and a target advertising those relevant operations. The current beta
qualification uses Docker Compose; no Kubernetes qualification is claimed.

## Register the destination

Keep manifest `schema_version: "1.0"` and choose `app.requires_core` for the verified target release as described in [contracts](contracts.md); the historical `">=1.3,<2.0"` range is limited to legacy Core 1.x.
An optional `internal_endpoints` entry has exactly these fields:

```json
{
  "internal_endpoints": [
    {"name": "actions", "kind": "mcp", "component": "backend", "path": "/mcp/"}
  ]
}
```

The name is a unique lowercase DNS label, up to 63 characters. The component must
be a declared backend with an HTTP port. The path is fixed, absolute and at most
512 ASCII characters from `/A-Za-z0-9._~-`; no query, fragment, encoded segments,
double slash or `.`/`..` traversal is permitted. A public application route is not
required for this endpoint. Do not supply a container host, private URL or port in
the endpoint declaration.

After installation, the logical reference is
`galene-app://<deployment UUID>/actions`. The authorized tenant operator creates
an HTTP connector through `POST /tenant/mcp-connectors`, tests/refreshes it through
the same public connector API and selects the tools to attach to an agent. Use
the request shapes and permissions in the snapshot. Installed connectors accept
no caller credentials, custom headers or external OAuth configuration. Never
derive the private network address in an app caller.

## Choose the caller authority

There are two distinct effectful principals:

- An application invokes approved tools through its own `mcp` service requirement,
  explicitly approved `mcp_tools`, and a bound `mcp_connector` resource. Core checks
  the current running service operation and its grants/schema pins. The provider
  receives the caller deployment/component/operation identifiers and no owner
  identity. It may reject this principal under its own business policy.
- An agent acts as its current owner only after that owner explicitly approves a
  bounded, revocable scope. Connecting a tool does not create this delegation.
  The grant permits offline work without storing or forwarding an owner bearer.

An owner reviews application, endpoint/version, exact selected tools and expiry
in the Console before confirming offline consent. The public API uses ordinary
tenant user authentication and `agent_owner_delegation.get`, `.approve` and
`.revoke` permissions:

1. `GET /agent/{agent_id}/owner-delegations` lists eligible installed destinations
   and the owner's consent records.
2. `POST /agent/{agent_id}/owner-delegations/preview` takes `mcp_connector_id`, exact
   unique `tool_ids` and timezone-aware `expires_at` within the next 30 days.
3. `POST /agent/{agent_id}/owner-delegations` repeats that request, the unchanged
   returned `scope_hash` and `offline_consent: true`.
4. `DELETE /agent/{agent_id}/owner-delegations/{delegation_id}` revokes the consent.

These endpoints return `WSResponse.result`. An identical approval retry returns
the same record; a changed scope requires another preview and replaces the old
unrevoked scope. API keys cannot approve this consent. Every use checks current
active owner, ownership, agent/connector/application access, connection
incarnation, destination/version, selected tools/schema pins, expiry and
revocation. Changed versions or schemas require a new review. Revocation denies
subsequent calls; it does not undo an already completed application action.

A direct user-mode `mcp.invoke` can nominate `arguments.agent_id` only with the
separate current `X-Galene-User-Authorization` bearer matching that agent owner and
an existing owner grant. An application-only caller cannot nominate an owner.
The agent runtime resolves its persisted grant without a human bearer. This MCP
authority never becomes general user authority for other Core services.

## Guard every incoming provider request

Core gives a registered MCP backend its own managed bootstrap credential even
when it declares no service requirements. This grants only the provider's own
authority introspection, with no implicit service access. Exchange it through
`POST /v1/services/token` as described in [application services](application-services.md).

Core attaches `X-Galene-MCP-Assertion` to MCP requests. Before any MCP effect, the
provider parses one bounded JSON-RPC request and calls
`POST /v1/services/mcp/introspect` using its own component access token:

```json
{"assertion":"<incoming assertion>","rpc_method":"tools/call","tool_name":"approved_action"}
```

Use the actual incoming method/tool name. For allowed non-effect methods omit
`tool_name`. The direct JSON response identifies the current provider target,
execution mode, expiry and approved tool/schema pin. Owner mode includes
`owner_user_id`, `agent_id` and `delegation_id`; application mode includes caller
deployment/component/operation. Catalog mode permits discovery only, never tool
effects. Accept only the methods documented in the snapshot; resource reads,
prompt execution and arbitrary batches are not covered by this tool consent.

Fail closed on invalid/expired assertions, a mismatched tenant, deployment,
component, endpoint or version, a denied RPC/tool, revoked/changed authority or
unavailable Core. Revalidate each RPC rather than caching an initial success for
the connection. Keep the target tied to trusted injected installation identity.
If an MCP SDK protects Host/Origin, configure it for the real installed listener;
a mounted private service must not inherit an unrelated localhost-only policy.
Preserve DNS/redirect and request-size protections.

The app must apply its own business permissions to this verified principal and
bound tool. An owner UUID supplied in caller JSON, an ordinary bearer sent to the
provider or a successful discovery request grants no authority. Never persist or
log the assertion, bearer, tool arguments/results or upstream library messages;
use [safe opaque diagnostics](logging.md).

## Private job callbacks

An entry with `kind: "callback"` declares a signed receiver on a backend port.
Use its logical reference in a `jobs.schedule` callback for the calling app's own
installation. Core denies references to another deployment and resolves current
installed state before delivery. Registration does not schedule work or grant a
job/service authority. Verify the signature, timestamp and replay identity as
described in [jobs and notifications](application-jobs-notifications.md); keep
the callback receiver's behavior equivalent to the public signed receiver.
