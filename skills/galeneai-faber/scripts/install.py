#!/usr/bin/env python3
"""Install a published app version using the selected tenant or publisher API."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

from _support import load_json, validate_project_context
from http_client import open_no_redirect

RequestJson = Callable[[str, str, str, str, dict[str, Any] | None], Any]


def _validated_base_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("base URL must use HTTPS (HTTP is allowed only on localhost)")
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("base URL must be an origin/path without user info, query, or fragment")
    return value.rstrip("/")


def request_json(
    base_url: str,
    path: str,
    token: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> Any:
    url = f"{_validated_base_url(base_url)}/{path.lstrip('/')}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with open_no_redirect(request, timeout=30) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"application API returned HTTP {exc.code}") from None
    except urllib.error.URLError:
        raise RuntimeError("application API request failed; check the endpoint and network") from None

    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RuntimeError("application API returned a non-JSON response") from None


def _target_schema(document: dict[str, Any], schema: Any) -> dict[str, Any]:
    """Resolve only local component schema references from the advertised contract."""
    seen: set[str] = set()
    while isinstance(schema, dict) and "$ref" in schema:
        reference = schema["$ref"]
        if (
            not isinstance(reference, str)
            or not reference.startswith("#/components/schemas/")
            or reference in seen
        ):
            raise RuntimeError("target OpenAPI has an unsupported application-service schema reference")
        seen.add(reference)
        schema = document["components"]["schemas"].get(reference.rsplit("/", 1)[-1])
    if not isinstance(schema, dict):
        raise RuntimeError("target OpenAPI is missing an application-service schema")
    return schema


def _target_properties(document: dict[str, Any], schema: Any) -> dict[str, Any]:
    properties = _target_schema(document, schema).get("properties")
    if not isinstance(properties, dict):
        raise RuntimeError("target OpenAPI is missing application-service schema fields")
    return properties


def verify_service_target(
    base_url: str,
    manifest: dict[str, Any] | None,
    *,
    auth_context: str = "publisher",
    api_request: RequestJson | None = None,
) -> None:
    """Fail closed for new requirements; Core still validates the full requires_core range."""
    if not manifest or not (
        manifest.get("service_requirements") or manifest.get("resource_requirements")
        or manifest.get("internal_endpoints")
    ):
        return
    requester = api_request or request_json
    document = requester(_validated_base_url(base_url), "/openapi.json", "", "GET", None)
    if not isinstance(document, dict):
        raise RuntimeError("target must advertise a verified Core 1.3 application-service contract")
    info = document.get("info")
    version = info.get("version") if isinstance(info, dict) else None
    release = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)", version) if isinstance(version, str) else None
    if not release or int(release[1]) != 1 or int(release[2]) < 3:
        raise RuntimeError("application services require a verified Core >=1.3,<2.0 target")
    if not str(document.get("openapi", "")).startswith("3."):
        raise RuntimeError("target OpenAPI does not expose the application-service contract")
    components = document.get("components")
    schemas = components.get("schemas") if isinstance(components, dict) else None
    if not isinstance(schemas, dict):
        raise RuntimeError("target OpenAPI is missing application-service schemas")
    manifest_fields = _target_properties(document, schemas.get("ApplicationManifest"))
    for field, required in (
        ("service_requirements", {
            "role": "string", "service": "string", "operations": "array",
            "resource_roles": "array", "execution_modes": "array",
        }),
        ("resource_requirements", {"role": "string", "kind": "string", "access": "string"}),
    ):
        requirement = _target_schema(document, manifest_fields.get(field))
        if requirement.get("type") != "array":
            raise RuntimeError("target OpenAPI is missing manifest service/resource requirements")
        fields = _target_properties(document, requirement.get("items"))
        if any(_target_schema(document, fields.get(name)).get("type") != kind for name, kind in required.items()):
            raise RuntimeError("target OpenAPI has an unsupported manifest requirement contract")
    paths = document.get("paths")
    if not isinstance(paths, dict):
        raise RuntimeError("target OpenAPI is missing application-service routes")
    if manifest.get("internal_endpoints"):
        endpoints = _target_schema(document, manifest_fields.get("internal_endpoints"))
        if endpoints.get("type") != "array":
            raise RuntimeError("target OpenAPI is missing installed application endpoints")
        endpoint = _target_schema(document, endpoints.get("items"))
        fields = _target_properties(document, endpoint)
        if set(fields) != {"name", "kind", "component", "path"} or endpoint.get("additionalProperties") is not False:
            raise RuntimeError("target OpenAPI has an unsupported installed endpoint contract")
        if any(_target_schema(document, field).get("type") != "string" for field in fields.values()):
            raise RuntimeError("target OpenAPI has an unsupported installed endpoint contract")
        if set(_target_schema(document, fields["kind"]).get("enum", [])) != {"mcp", "callback"}:
            raise RuntimeError("target OpenAPI has an unsupported installed endpoint kind")
        if any(item.get("kind") == "mcp" for item in manifest["internal_endpoints"] if isinstance(item, dict)):
            introspection = paths.get("/v1/services/mcp/introspect")
            if not isinstance(introspection, dict) or not isinstance(introspection.get("post"), dict):
                raise RuntimeError("target OpenAPI is missing installed MCP authority introspection")
    for path, methods in (
        ("/v1/services/token", ("post",)),
        ("/v1/services/grants", ("get",)),
        ("/v1/services/operations", ("post", "get")),
        ("/v1/services/operations/{operation_id}", ("get",)),
        ("/v1/services/operations/{operation_id}/cancel", ("post",)),
        ("/v1/services/operations/{operation_id}/artifacts/{name}", ("get",)),
    ):
        if not isinstance(paths.get(path), dict) or not all(
            isinstance(paths[path].get(method), dict) for method in methods
        ):
            raise RuntimeError("target OpenAPI is missing application-service routes")
    install_path = (
        "/tenant/applications/deployments" if auth_context == "tenant"
        else "/controlplane/tenants/{tenant_id}/application-deployments"
    )
    route = paths.get(install_path)
    operation = route.get("post") if isinstance(route, dict) else None
    body = operation.get("requestBody") if isinstance(operation, dict) else None
    content = body.get("content") if isinstance(body, dict) else None
    media = content.get("application/json") if isinstance(content, dict) else None
    request_schema = media.get("schema") if isinstance(media, dict) else None
    fields = _target_properties(document, request_schema)
    approvals = _target_schema(document, fields.get("approved_services"))
    bindings = _target_schema(document, fields.get("service_bindings"))
    if approvals.get("type") != "array" or (
        _target_schema(document, approvals.get("items")).get("type") != "string"
    ):
        raise RuntimeError("target OpenAPI is missing explicit application-service approvals")
    if bindings.get("type") != "object":
        raise RuntimeError("target OpenAPI is missing explicit application-service resource bindings")
    binding_schema = _target_schema(document, bindings.get("additionalProperties"))
    binding_fields = _target_properties(document, binding_schema)
    if set(binding_fields) != {"resource_id", "access"} or binding_schema.get("additionalProperties") is not False:
        raise RuntimeError("target OpenAPI has an unsupported public application-service binding contract")
    resource_id = _target_schema(document, binding_fields.get("resource_id"))
    access = _target_schema(document, binding_fields.get("access"))
    if (
        resource_id.get("type") != "string" or resource_id.get("format") != "uuid"
        or access.get("type") != "string" or access.get("enum") not in (
            ["read", "read_write"], ["read_write", "read"]
        )
    ):
        raise RuntimeError("target OpenAPI has an unsupported application-service binding contract")


def _result(body: Any) -> Any:
    if isinstance(body, dict):
        if body.get("success") is False:
            raise RuntimeError("application API rejected the request")
        return body.get("result", body)
    return body


def _collection(body: Any, description: str) -> list[dict[str, Any]]:
    value = _result(body)
    if isinstance(value, dict):
        value = value.get("items")
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise RuntimeError(f"application API {description} response has an unsupported shape")
    return value


def _matches_available(
    items: list[dict[str, Any]], package_id: str, version_id: str, slug: str, app_version: str
) -> bool:
    for item in items:
        package = item.get("package")
        version = item.get("version")
        if not isinstance(package, dict) or not isinstance(version, dict):
            continue
        if (
            str(package.get("id")) == package_id
            and str(version.get("id")) == version_id
            and package.get("slug") == slug
            and version.get("version") == app_version
        ):
            return True
    return False


def _publisher_targets(
    api_request: RequestJson,
    base_url: str,
    token: str,
    tenant: str,
    package_id: str,
    version_id: str,
    slug: str,
    app_version: str,
) -> tuple[str, str, str]:
    tenant_rows = _collection(
        api_request(base_url, "/controlplane/tenants", token, "GET", None),
        "tenant catalog",
    )
    tenant_row = next((row for row in tenant_rows if row.get("slug") == tenant), None)
    if tenant_row is None:
        raise RuntimeError("selected tenant was not found in the publisher tenant catalog")
    tenant_id = str(tenant_row.get("id", ""))
    try:
        tenant_id = str(uuid.UUID(tenant_id))
        package_id = str(uuid.UUID(package_id))
        version_id = str(uuid.UUID(version_id))
    except ValueError:
        raise RuntimeError("tenant, package, and version IDs must be valid UUIDs") from None

    packages = _collection(
        api_request(base_url, "/controlplane/applications", token, "GET", None),
        "app package catalog",
    )
    package = next(
        (row for row in packages if str(row.get("id")) == package_id and row.get("slug") == slug),
        None,
    )
    if package is None:
        raise RuntimeError("selected package ID does not match the app manifest slug")

    versions = _collection(
        api_request(
            base_url,
            f"/controlplane/applications/{package_id}/versions",
            token,
            "GET",
            None,
        ),
        "app version catalog",
    )
    version = next(
        (row for row in versions if str(row.get("id")) == version_id and row.get("version") == app_version),
        None,
    )
    if version is None:
        raise RuntimeError("selected version ID does not match the requested app SemVer")

    return tenant_id, package_id, version_id


def _required_domain_routes(routes: list[dict[str, Any]] | None) -> list[tuple[str, str]]:
    required: list[tuple[str, str]] = []
    for route in routes or []:
        if not isinstance(route, dict) or route.get("host_required", True) is False:
            continue
        component = route.get("component")
        role = route.get("role", "frontend")
        if not isinstance(component, str) or not isinstance(role, str):
            raise ValueError("host-required manifest routes need component and role names")
        if role not in {"frontend", "api", "webhook"}:
            raise ValueError(f"unsupported route role for host binding: {role}")
        key = (component, role)
        if key not in required:
            required.append(key)
    return required


def _publisher_domain_bindings(
    api_request: RequestJson,
    base_url: str,
    token: str,
    tenant_id: str,
    routes: list[dict[str, Any]] | None,
    selections: dict[tuple[str, str], str],
) -> list[tuple[str, str, str, str]]:
    required = _required_domain_routes(routes)
    if not required:
        if selections:
            raise ValueError("domain bindings were supplied but the manifest has no host-required routes")
        return []

    options = _collection(
        api_request(
            base_url,
            f"/controlplane/tenants/{tenant_id}/application-domain-options",
            token,
            "GET",
            None,
        ),
        "tenant application-domain options",
    )
    normalized_options: dict[str, dict[str, Any]] = {}
    for option in options:
        option_id = option.get("id")
        host = option.get("host")
        if not isinstance(option_id, str) or not isinstance(host, str):
            raise RuntimeError("application-domain options response is missing id or host")
        try:
            normalized_options[str(uuid.UUID(option_id))] = option
        except ValueError:
            raise RuntimeError("application-domain options response contains an invalid ID") from None

    unknown_routes = sorted(set(selections) - set(required))
    if unknown_routes:
        labels = ", ".join(f"{component}:{role}" for component, role in unknown_routes)
        raise ValueError(f"domain selections do not match host-required manifest routes: {labels}")
    missing = [key for key in required if key not in selections]
    invalid_ids = []
    for key in required:
        if key not in selections:
            continue
        try:
            domain_id = str(uuid.UUID(selections[key]))
        except ValueError:
            raise ValueError(f"domain ID for {key[0]}:{key[1]} must be a UUID") from None
        if domain_id not in normalized_options:
            invalid_ids.append(f"{key[0]}:{key[1]}={domain_id}")
        else:
            selections[key] = domain_id
    if missing or invalid_ids:
        choices = ", ".join(
            f"{domain_id} ({option['host']})"
            for domain_id, option in sorted(normalized_options.items())
        ) or "no managed domains are available"
        problems = []
        if missing:
            problems.append(
                "select a domain for " + ", ".join(f"{component}:{role}" for component, role in missing)
            )
        if invalid_ids:
            problems.append("unavailable domain selections: " + ", ".join(invalid_ids))
        raise ValueError("; ".join(problems) + f". Tenant options: {choices}")

    return [
        (component, role, selections[(component, role)], normalized_options[selections[(component, role)]]["host"])
        for component, role in required
    ]


_SERVICE_ROLE = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")


def _declared_roles(manifest: dict[str, Any], field: str) -> dict[str, dict[str, Any]]:
    entries = manifest.get(field, [])
    if not isinstance(entries, list):
        raise ValueError(f"manifest {field} must be a list")
    roles = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("role"), str) or not _SERVICE_ROLE.fullmatch(entry["role"]):
            raise ValueError(f"manifest {field} contains an invalid role")
        if entry["role"] in roles:
            raise ValueError(f"manifest {field} contains duplicate roles")
        roles[entry["role"]] = entry
    return roles


def _service_selections(manifest, approved_services, service_bindings) -> dict[str, Any]:
    if manifest is None:
        if approved_services is not None or service_bindings is not None:
            raise ValueError("service selections require the manifest")
        return {}
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    services = _declared_roles(manifest, "service_requirements")
    resources = _declared_roles(manifest, "resource_requirements")
    if approved_services is not None and not isinstance(approved_services, list):
        raise ValueError("approved_services must be a list")
    approved = approved_services if approved_services is not None else []
    seen = set()
    for role in approved:
        if not isinstance(role, str) or not _SERVICE_ROLE.fullmatch(role) or role not in services:
            raise ValueError("approved service must name a declared manifest role")
        if role in seen:
            raise ValueError("approved service selections must be unique")
        seen.add(role)
    if any(spec.get("required", False) and role not in seen for role, spec in services.items()):
        raise ValueError("explicitly approve every required service; no services are granted automatically")
    if service_bindings is not None and not isinstance(service_bindings, dict):
        raise ValueError("service_bindings must be an object keyed by manifest resource role")
    bindings = {}
    for role, binding in (service_bindings or {}).items():
        if not isinstance(role, str) or not _SERVICE_ROLE.fullmatch(role) or role not in resources:
            raise ValueError("binding must name a declared manifest resource role")
        if not isinstance(binding, dict) or set(binding) != {"resource_id", "access"}:
            raise ValueError("each binding must contain only resource_id and access")
        if not isinstance(binding["resource_id"], str):
            raise ValueError("binding resource_id must be a UUID string")
        try:
            resource_id = str(uuid.UUID(binding["resource_id"]))
        except ValueError:
            raise ValueError("binding resource_id must be a UUID string") from None
        access = binding["access"]
        spec = resources[role]
        if not isinstance(access, str) or access not in {"read", "read_write"}:
            raise ValueError("binding access must be read or read_write")
        if access == "read_write" and (spec.get("kind") != "filesystem" or spec.get("access", "read") != "read_write"):
            raise ValueError("binding write access exceeds the declared resource access")
        bindings[role] = {"resource_id": resource_id, "access": access}
    required_resources = {role for role, spec in resources.items() if spec.get("required", False)}
    for role in approved:
        dependencies = services[role].get("resource_roles", [])
        if not isinstance(dependencies, list) or any(not isinstance(item, str) or item not in resources for item in dependencies):
            raise ValueError("approved service references invalid resource roles")
        required_resources.update(dependencies)
    if not required_resources.issubset(bindings):
        raise ValueError("bind every required resource and every approved service resource role")
    selections = {}
    if approved_services is not None:
        selections["approved_services"] = list(approved)
    if service_bindings is not None:
        selections["service_bindings"] = bindings
    return selections


def _load_service_bindings(path: Path) -> dict[str, Any]:
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("service bindings JSON contains duplicate keys")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
    except json.JSONDecodeError:
        raise ValueError("service bindings file must contain valid JSON") from None
    if not isinstance(value, dict):
        raise ValueError("service bindings file must contain a resource-role mapping")
    return value


def install_deployment(
    *,
    base_url: str,
    tenant: str,
    project_tenant: str,
    package_id: str,
    version_id: str,
    slug: str,
    app_version: str,
    token: str,
    auth_context: str = "tenant",
    deployment_name: str | None = None,
    routes: list[dict[str, Any]] | None = None,
    domain_bindings: dict[tuple[str, str], str] | None = None,
    manifest: dict[str, Any] | None = None,
    approved_services: list[str] | None = None,
    service_bindings: dict[str, dict[str, str]] | None = None,
    api_request: RequestJson = request_json,
) -> Any:
    if tenant != project_tenant:
        raise ValueError("selected tenant does not match galene-app-project.json")
    if auth_context not in {"tenant", "publisher"}:
        raise ValueError("auth_context must be tenant or publisher")
    base_url = _validated_base_url(base_url)
    domain_bindings = dict(domain_bindings or {})

    payload: dict[str, Any] = {"package_id": package_id, "version_id": version_id}
    if deployment_name:
        payload["deployment_name"] = deployment_name
    payload.update(_service_selections(manifest, approved_services, service_bindings))
    verify_service_target(base_url, manifest, auth_context=auth_context, api_request=api_request)

    if auth_context == "tenant":
        required_routes = _required_domain_routes(routes)
        if required_routes:
            raise ValueError(
                "host-required routes need publisher domain selection or completion in the tenant application UI"
            )
        if domain_bindings:
            raise ValueError("domain bindings are only supported by the publisher API flow")
        available = api_request(base_url, "/tenant/applications/available", token, "GET", None)
        if not _matches_available(_collection(available, "available-app"), package_id, version_id, slug, app_version):
            raise RuntimeError("the selected package/version is not available to this authenticated tenant")
        path = "/tenant/applications/deployments"
    else:
        tenant_id, package_id, version_id = _publisher_targets(
            api_request, base_url, token, tenant, package_id, version_id, slug, app_version
        )
        domain_plan = _publisher_domain_bindings(
            api_request, base_url, token, tenant_id, routes, domain_bindings
        )
        payload["package_id"] = package_id
        path = f"/controlplane/tenants/{tenant_id}/application-deployments"
    if auth_context == "tenant":
        domain_plan = []

    result = api_request(base_url, path, token, "POST", payload)
    deployment = _result(result)
    if domain_plan and not isinstance(deployment, dict):
        raise RuntimeError("deployment was created but the API returned no deployment object; complete required domains in the Control Plane")
    if domain_plan and isinstance(deployment, dict):
        deployment_id = deployment.get("id")
        try:
            deployment_id = str(uuid.UUID(str(deployment_id)))
        except ValueError:
            raise RuntimeError("deployment was created but returned an invalid deployment ID; complete domain binding in the Control Plane") from None
        bound = []
        for component, role, domain_id, host in domain_plan:
            try:
                binding = _result(
                    api_request(
                        base_url,
                        f"/controlplane/application-deployments/{deployment_id}/domains",
                        token,
                        "POST",
                        {
                            "component_name": component,
                            "route_role": role,
                            "managed_domain_id": domain_id,
                        },
                    )
                )
            except RuntimeError:
                raise RuntimeError(
                    f"deployment {deployment_id} was created, but binding {component}:{role} to {host} failed; finish the route in the Control Plane"
                ) from None
            bound.append({"component_name": component, "route_role": role, "host": host, "binding": binding})
        deployment["domain_bindings"] = bound
    return deployment


def _parse_domain_bindings(values: list[str]) -> dict[tuple[str, str], str]:
    parsed: dict[tuple[str, str], str] = {}
    for value in values:
        route_key, separator, domain_id = value.partition("=")
        component, colon, role = route_key.rpartition(":")
        if not separator or not colon or not component or not role or not domain_id:
            raise ValueError("domain binding must be COMPONENT:ROLE=MANAGED_DOMAIN_ID")
        key = (component, role)
        if key in parsed:
            raise ValueError(f"duplicate domain binding selector for {component}:{role}")
        parsed[key] = domain_id
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--base-url", required=True, help="Galene API origin or API base path")
    parser.add_argument("--tenant", required=True, help="explicit tenant slug selected in the blueprint")
    parser.add_argument("--auth-context", choices=("tenant", "publisher"), default="tenant")
    parser.add_argument("--app-version", required=True, help="published SemVer to install")
    parser.add_argument("--package-id", required=True)
    parser.add_argument("--version-id", required=True)
    parser.add_argument("--deployment-name")
    parser.add_argument(
        "--approved-service", action="append", metavar="ROLE",
        help="explicitly approve a manifest service role; repeat for each selection (no automatic grants)",
    )
    parser.add_argument(
        "--service-bindings", type=Path, metavar="JSON_FILE",
        help="JSON mapping of manifest resource roles to {resource_id: UUID, access: read|read_write}",
    )
    parser.add_argument(
        "--domain-binding",
        action="append",
        default=[],
        metavar="COMPONENT:ROLE=MANAGED_DOMAIN_ID",
        help="select an offered tenant domain for each host-required route (publisher flow)",
    )
    args = parser.parse_args()

    try:
        project = args.project.resolve()
        context = load_json(project / "galene-app-project.json")
        errors = validate_project_context(context)
        if errors:
            raise ValueError("invalid project context: " + "; ".join(errors))
        manifest = load_json(project / "galene-app.json")
        token_name = "GALENE_TENANT_TOKEN" if args.auth_context == "tenant" else "GALENE_CONTROLPLANE_TOKEN"
        token = os.environ.get(token_name, "")
        if not token:
            raise ValueError(f"set {token_name} from the approved secret manager/environment")
        result = install_deployment(
            base_url=args.base_url,
            tenant=args.tenant,
            project_tenant=context["tenant"]["slug"],
            package_id=args.package_id,
            version_id=args.version_id,
            slug=manifest["app"]["slug"],
            app_version=args.app_version,
            token=token,
            auth_context=args.auth_context,
            deployment_name=args.deployment_name,
            routes=manifest.get("routes", []),
            domain_bindings=_parse_domain_bindings(args.domain_binding),
            manifest=manifest,
            approved_services=args.approved_service,
            service_bindings=_load_service_bindings(args.service_bindings) if args.service_bindings else None,
        )
    except (KeyError, ValueError, RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    safe_fields = {
        key: result[key]
        for key in ("id", "status", "desired_status")
        if isinstance(result, dict) and key in result
    }
    print(f"Install requested for tenant {args.tenant}, app {args.app_version}.")
    if safe_fields:
        print(json.dumps(safe_fields, sort_keys=True))
    else:
        print("Application API accepted the install request.")
    print("Check deployment readiness and run the approved primary workflow in the tenant.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
