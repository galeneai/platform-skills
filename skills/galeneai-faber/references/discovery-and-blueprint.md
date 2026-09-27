# Discovery and blueprint

Use a short conversation to identify the work the app should make easier. Ask only for facts that affect the product: who uses it, what they do today, where the current process fails, which data the app handles, and what observable result would make the first release useful.

Every project must name a target tenant and environment, and choose one image registry:
- an owner-managed external OCI registry;
- Galene's integrated registry.

Ask these choices even when an earlier project or local credentials suggest an answer. Record the tenant slug/environment and registry mode in the app's private project context. Never record registry passwords or tokens.

## Approval point

Before implementation, present a brief blueprint for approval. Keep it to the decisions the user needs to confirm:

- business need, target user, and current workflow;
- first useful workflow and acceptance result;
- target tenant/environment and registry mode;
- proposed app components and Galene features/capabilities;
- tenant data, roles, permissions, secrets, and app database needs;
- compatibility baseline and Compose/Kubernetes behavior;
- release and installation boundary.

State assumptions plainly. Do not turn the blueprint into a full technical dossier. Do not begin implementation until the user approves it. After approval, continue through the agreed release and tenant installation when that is in scope. Ask again only if a proposed requirement would expand the approved outcome; resolve routine implementation choices directly.

## After approval

Follow [application delivery](application-delivery.md): check the relevant public prerequisites, complete a small real user workflow, then expand coverage. Use focused tests for decision logic, tenant isolation, authorization, persistence, and migration safety; direct verification can be enough for simple UI or configuration changes. Run expensive corpus-wide acceptance after the workflow is stable, and repeat only the checks affected by a later fix.

If the user has not authorized installation or has not named a tenant, keep the release bundle ready and ask for that missing decision before the install write.
