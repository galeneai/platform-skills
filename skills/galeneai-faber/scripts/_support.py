"""Shared offline helpers for the galeneai-faber skill."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = SKILL_ROOT / "references" / "contracts"
MANIFEST_SCHEMA = CONTRACTS / "application-manifest.schema.json"
PROJECT_SCHEMA = CONTRACTS / "galene-app-project.schema.json"
SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
IMAGE_DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")
SOURCE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc


def validator_for(schema_path: Path):
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as exc:
        raise RuntimeError(
            "jsonschema is required; install scripts/requirements.txt"
        ) from exc

    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _error_order(error: Any) -> tuple[str, ...]:
    return tuple(f"{type(part).__name__}:{part}" for part in error.absolute_path)


def format_error(error: Any) -> str:
    location = ".".join(str(part) for part in error.absolute_path)
    prefix = f"{location}: " if location else ""
    return prefix + error.message


def validate_project_context(value: Any) -> list[str]:
    validator = validator_for(PROJECT_SCHEMA)
    return [
        format_error(error)
        for error in sorted(validator.iter_errors(value), key=_error_order)
    ]


def _strings(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str)}


def validate_manifest(
    value: Any, *, flow: str = "version", require_digests: bool = False
) -> list[str]:
    if flow not in {"version", "archive-import"}:
        raise ValueError("flow must be version or archive-import")

    validator = validator_for(MANIFEST_SCHEMA)
    errors = [
        format_error(error)
        for error in sorted(validator.iter_errors(value), key=_error_order)
    ]
    if not isinstance(value, dict):
        return errors

    components = value.get("components")
    if not isinstance(components, list):
        return errors

    names = [
        item["name"]
        for item in components
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    ]
    component_names = set(names)
    if len(names) != len(set(names)):
        errors.append("components: names must be unique")

    archive_targets: list[str] = []
    archive_registry_ids: list[Any] = []
    env_names: set[tuple[str, str]] = set()
    for component in components:
        if not isinstance(component, dict):
            continue
        name = component.get("name")
        if isinstance(component.get("archive_import"), dict):
            archive_targets.append(name)
            archive_registry_ids.append(component["archive_import"].get("registry_source_id"))

        env_schema = component.get("env_schema", [])
        if not isinstance(env_schema, list):
            env_schema = []
        for env_spec in env_schema:
            if not isinstance(env_spec, dict):
                continue
            env_name = env_spec.get("name")
            if not isinstance(name, str) or not isinstance(env_name, str):
                continue
            key = (name, env_name)
            if key in env_names:
                errors.append(f"components.{name}.env_schema: duplicate environment name {env_name}")
            env_names.add(key)

        connectivity = component.get("connectivity", {})
        if isinstance(connectivity, dict):
            missing = sorted(_strings(connectivity.get("depends_on", [])) - component_names)
            if missing:
                errors.append(f"components.{name}.connectivity.depends_on: unknown components {', '.join(missing)}")

        if require_digests:
            image = component.get("image")
            source = component.get("image_source")
            if isinstance(image, str) and not IMAGE_DIGEST.search(image):
                errors.append(f"components.{name}.image: released images must be pinned to sha256 digest")
            if isinstance(source, dict) and not SOURCE_DIGEST.fullmatch(str(source.get("reference", ""))):
                errors.append(f"components.{name}.image_source.reference: released images must be pinned to sha256 digest")

    if flow == "version" and archive_targets:
        errors.append("components: archive_import is accepted only by the archive-import flow")
    if flow == "archive-import" and not archive_targets:
        errors.append("components: integrated archive import requires at least one archive_import component")
    if flow == "archive-import" and archive_targets:
        valid_registry_ids = {
            source_id for source_id in archive_registry_ids if isinstance(source_id, str)
        }
        if len(valid_registry_ids) != 1 or len(archive_registry_ids) != len(archive_targets):
            errors.append("components: all archive_import components must use the same registry_source_id")

    routes = value.get("routes", [])
    if not isinstance(routes, list):
        routes = []
    for index, route in enumerate(routes):
        component = route.get("component") if isinstance(route, dict) else None
        if isinstance(component, str) and component not in component_names:
            errors.append(f"routes[{index}].component: unknown component")

    endpoints = value.get("internal_endpoints", [])
    if isinstance(endpoints, list):
        endpoint_names: set[str] = set()
        component_by_name = {
            item.get("name"): item for item in components
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        for index, endpoint in enumerate(endpoints):
            if not isinstance(endpoint, dict):
                continue
            name = endpoint.get("name")
            if isinstance(name, str):
                if name in endpoint_names:
                    errors.append(f"internal_endpoints[{index}].name: names must be unique")
                endpoint_names.add(name)
            target = component_by_name.get(endpoint.get("component")) if isinstance(endpoint.get("component"), str) else None
            if target is None:
                errors.append(f"internal_endpoints[{index}].component: unknown component")
            elif target.get("kind") != "backend" or not target.get("port"):
                errors.append(f"internal_endpoints[{index}].component: a backend with a port is required")

    capabilities = value.get("capabilities", [])
    if not isinstance(capabilities, list):
        capabilities = []
    for index, capability in enumerate(capabilities):
        if not isinstance(capability, dict):
            continue
        missing = sorted(_strings(capability.get("target_components", [])) - component_names)
        if missing:
            errors.append(f"capabilities[{index}].target_components: unknown components {', '.join(missing)}")

    database_resources = value.get("database_resources", [])
    if not isinstance(database_resources, list):
        database_resources = []
    for index, resource in enumerate(database_resources):
        if not isinstance(resource, dict):
            continue
        missing = sorted(_strings(resource.get("target_components", [])) - component_names)
        if missing:
            errors.append(f"database_resources[{index}].target_components: unknown components {', '.join(missing)}")

    model_requirements = value.get("model_requirements")
    if not isinstance(model_requirements, list):
        model_requirements = []
    for index, requirement in enumerate(model_requirements):
        if not isinstance(requirement, dict):
            continue
        for target in requirement.get("env", []):
            component = target.get("component") if isinstance(target, dict) else None
            if isinstance(component, str) and component not in component_names:
                errors.append(f"model_requirements[{index}].env: unknown component {component}")

    return errors


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def manifest_warnings(value: Any) -> list[str]:
    """Non-blocking findings for patterns that pass the schema but fail on real clusters.

    See references/runtime-readiness.md. These never make validation fail.
    """
    warnings: list[str] = []
    if not isinstance(value, dict) or not isinstance(value.get("components"), list):
        return warnings
    components = [item for item in value["components"] if isinstance(item, dict)]
    names = {item.get("name") for item in components if isinstance(item.get("name"), str)}
    for component in components:
        name = component.get("name")
        if not isinstance(name, str):
            continue
        volume = component.get("persistent_volume")
        if isinstance(volume, dict) and not volume.get("storage_class"):
            warnings.append(
                f"components.{name}.persistent_volume: no storage_class; on a cluster without a default "
                "StorageClass the pod stays Pending. Prefer the app database or object storage, or document the prerequisite"
            )
        connectivity = component.get("connectivity")
        depends = []
        if isinstance(connectivity, dict) and isinstance(connectivity.get("depends_on"), list):
            depends = [item for item in connectivity["depends_on"] if isinstance(item, str) and item in names]
        env_schema = component.get("env_schema")
        for env_spec in env_schema if isinstance(env_schema, list) else []:
            if not isinstance(env_spec, dict) or not isinstance(env_spec.get("name"), str):
                continue
            env_name = env_spec["name"]
            required = env_spec.get("required") is True
            if required and not env_spec.get("sensitive") and env_spec.get("default") in (None, ""):
                hint = ""
                if depends and any(token in env_name.upper() for token in ("ORIGIN", "URL", "UPSTREAM", "BACKEND", "API")):
                    hint = (
                        "; the platform injects GALENE_COMPONENT_<NAME>_URL for "
                        + ", ".join(sorted(depends))
                        + ": use it as the default"
                    )
                warnings.append(
                    f"components.{name}.env_schema.{env_name}: required with no default, so the installer must type it"
                    f"{hint}. Derive it or give a default when the platform already knows the value"
                )
            default = env_spec.get("default")
            if isinstance(default, str) and any(token in default for token in ("test-tenant", ".elettra.ai", "api-beta")):
                warnings.append(
                    f"components.{name}.env_schema.{env_name}: the default looks like a lab value; ship neutral defaults"
                )
    return warnings
