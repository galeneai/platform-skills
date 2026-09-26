#!/usr/bin/env python3
"""Create a deterministic app release bundle without a Galene stack."""

from __future__ import annotations

import argparse
import gzip
import io
import hashlib
import json
import re
import sys
import tarfile
from pathlib import Path
from typing import Any

from _support import (
    CONTRACTS,
    SEMVER,
    canonical_json,
    load_json,
    validate_manifest,
    validate_project_context,
)

HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")


def _release_files(project: Path, version: str) -> dict[str, bytes]:
    if not SEMVER.fullmatch(version):
        raise ValueError("version must follow SemVer, for example 1.2.0 or 1.2.0-rc.1")

    manifest = load_json(project / "galene-app.json")
    context = load_json(project / "galene-app-project.json")
    errors = validate_project_context(context)
    if errors:
        raise ValueError("invalid project context: " + "; ".join(errors))

    registry_choice = context["registry"]["choice"]
    flow = "archive-import" if registry_choice == "integrated" else "version"
    errors = validate_manifest(manifest, flow=flow, require_digests=True)
    if errors:
        raise ValueError("invalid release manifest: " + "; ".join(errors))

    if registry_choice == "integrated" and not any(
        isinstance(component, dict) and isinstance(component.get("archive_import"), dict)
        for component in manifest["components"]
    ):
        raise ValueError("integrated registry releases require at least one archive_import component")

    compatibility_path = project / "compatibility.json"
    compatibility = load_json(compatibility_path)
    if not isinstance(compatibility, dict):
        raise ValueError("compatibility.json must contain an object")
    if compatibility.get("app_version") != version:
        raise ValueError("compatibility.json app_version must match --version")
    if compatibility.get("manifest_schema") != manifest.get("schema_version"):
        raise ValueError("compatibility.json manifest_schema must match the manifest")
    if not HEX_40.fullmatch(str(compatibility.get("platform_core_commit", ""))):
        raise ValueError("compatibility.json must name a full committed Platform Core SHA")
    for field in ("manifest_schema_sha256", "openapi_sha256"):
        if not HEX_64.fullmatch(str(compatibility.get(field, ""))):
            raise ValueError(f"compatibility.json {field} must be a 64-character SHA-256")
    snapshot = load_json(CONTRACTS / "snapshot-lock.json")
    contract_files = {
        "application_manifest_json_schema": CONTRACTS / "application-manifest.schema.json",
        "app_api_openapi": CONTRACTS / "application-api.openapi.yaml",
    }
    for contract_name, contract_path in contract_files.items():
        actual_hash = hashlib.sha256(contract_path.read_bytes()).hexdigest()
        expected_hash = snapshot["contracts"][contract_name]["sha256"]
        if actual_hash != expected_hash:
            raise ValueError(f"pinned {contract_name} artifact does not match snapshot-lock.json")
    pinned = {
        "platform_core_commit": snapshot["source"]["commit"],
        "manifest_schema_sha256": snapshot["contracts"]["application_manifest_json_schema"]["sha256"],
        "openapi_sha256": snapshot["contracts"]["app_api_openapi"]["sha256"],
    }
    for field, expected in pinned.items():
        if compatibility.get(field) != expected:
            raise ValueError(f"compatibility.json {field} must match the pinned contract snapshot")
    if compatibility.get("registry_mode") != registry_choice:
        raise ValueError("compatibility.json registry_mode must match galene-app-project.json")

    manifest_bytes = canonical_json(manifest)
    release_metadata: dict[str, Any] = {
        "app_slug": manifest["app"]["slug"],
        "app_version": version,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "platform_core_commit": compatibility["platform_core_commit"],
        "manifest_schema_sha256": compatibility["manifest_schema_sha256"],
        "openapi_sha256": compatibility["openapi_sha256"],
        "registry_mode": registry_choice,
        "runtime_adapters": compatibility.get("runtime_adapters", {}),
    }

    files = {
        "manifest.json": manifest_bytes,
        "compatibility.json": canonical_json(compatibility),
        "release-metadata.json": canonical_json(release_metadata),
    }
    notes = project / "release-notes.md"
    if notes.is_file():
        files["release-notes.md"] = notes.read_bytes()
    return files


def build_bundle(project: Path, version: str, output: Path, *, force: bool = False) -> Path:
    files = _release_files(project, version)
    output = output.resolve()
    if output.exists() and not force:
        raise FileExistsError(f"output already exists: {output} (pass --force to replace it)")
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for name, data in sorted(files.items()):
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    info.mtime = 0
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    info.mode = 0o644
                    archive.addfile(info, io.BytesIO(data))
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--version", required=True, help="immutable app SemVer")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--force", action="store_true", help="replace an existing output bundle")
    args = parser.parse_args()

    project = args.project.resolve()
    try:
        manifest = load_json(project / "galene-app.json")
        output = args.output or Path("dist") / f"{manifest['app']['slug']}-{args.version}.tar.gz"
        result = build_bundle(project, args.version, output, force=args.force)
    except (KeyError, ValueError, RuntimeError, FileExistsError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Created {result}")
    print("The bundle contains manifest and release metadata only; component images remain in the selected OCI registry.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
