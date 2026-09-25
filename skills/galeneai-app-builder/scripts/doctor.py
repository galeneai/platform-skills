#!/usr/bin/env python3
"""Check a Galene app project without starting a platform stack."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _support import (
    MANIFEST_SCHEMA,
    PROJECT_SCHEMA,
    load_json,
    validate_manifest,
    validate_project_context,
)


def doctor(project: Path) -> list[str]:
    issues: list[str] = []
    if sys.version_info < (3, 10):
        issues.append("Python 3.10 or newer is required")

    manifest_path = project / "galene-app.json"
    project_path = project / "galene-app-project.json"
    if not manifest_path.is_file():
        issues.append(f"missing {manifest_path.name}")
    if not project_path.is_file():
        issues.append(f"missing {project_path.name}; record tenant and registry choice")

    for schema in (MANIFEST_SCHEMA, PROJECT_SCHEMA):
        if not schema.is_file():
            issues.append(f"missing skill contract file: {schema.name}")

    if not issues:
        try:
            manifest = load_json(manifest_path)
            context = load_json(project_path)
            context_errors = validate_project_context(context)
            issues.extend(f"project context: {item}" for item in context_errors)
            registry = context.get("registry") if isinstance(context, dict) else None
            flow = (
                "archive-import"
                if not context_errors and isinstance(registry, dict)
                and registry.get("choice") == "integrated"
                else "version"
            )
            issues.extend(
                f"manifest: {item}"
                for item in validate_manifest(manifest, flow=flow)
            )
        except RuntimeError as exc:
            issues.append(str(exc))
        except ValueError as exc:
            issues.append(str(exc))

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="app project directory")
    args = parser.parse_args()

    issues = doctor(args.project.resolve())
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}", file=sys.stderr)
        return 1

    print("OK: local app files and manifest are valid; no Galene stack was contacted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
