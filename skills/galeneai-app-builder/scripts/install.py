#!/usr/bin/env python3
"""Install a published app version using the selected tenant or publisher API."""

from __future__ import annotations

import argparse
import json
import os
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
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
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
