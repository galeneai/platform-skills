#!/usr/bin/env python3
"""Validate a manifest offline and, when available, through Platform Core."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from _support import load_json, validate_manifest
from http_client import open_no_redirect
from install import _validated_base_url


def server_validate(
    base_url: str, token: str, package_slug: str, version: str, manifest: dict[str, Any]
) -> dict[str, Any]:
    url = f"{_validated_base_url(base_url)}/controlplane/application-manifests/validate"
    body = json.dumps(
        {"package_slug": package_slug, "version": version, "manifest": manifest}
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with open_no_redirect(request, timeout=30) as response:
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
    except urllib.error.URLError:
        raise RuntimeError("Core validation request failed; check endpoint and network") from None

    if status == 404:
        raise RuntimeError("server-side validator is not available on this Core version; refresh the pinned contract snapshot")
    if status not in {200, 422}:
        raise RuntimeError(f"Core validation API returned HTTP {status}")
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RuntimeError("Core validation API returned a non-JSON response") from None
    if not isinstance(result, dict) or not isinstance(result.get("valid"), bool) or not isinstance(result.get("errors"), list):
        raise RuntimeError("Core validation API returned an unsupported response shape")
    if status == 200 and not result["valid"]:
        raise RuntimeError("Core returned an invalid 200 validation response")
    if status == 422 and result["valid"]:
        raise RuntimeError("Core returned a valid 422 validation response")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, nargs="?", default=Path("galene-app.json"))
    parser.add_argument(
        "--flow",
        choices=("version", "archive-import"),
        default="version",
        help="new version publication or integrated registry archive import",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help="require every component image reference to resolve to a sha256 digest",
    )
    parser.add_argument("--server-url", help="opt in to the committed Core server validator")
    parser.add_argument("--version", help="app SemVer; required with --server-url")
    parser.add_argument("--package-slug", help="defaults to manifest app.slug")
    args = parser.parse_args()

    try:
        manifest = load_json(args.manifest)
        errors = validate_manifest(manifest, flow=args.flow, require_digests=args.release)
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print("Offline schema checks do not replace server-side publication validation.", file=sys.stderr)
        return 1

    if args.server_url and args.flow == "archive-import":
        print(
            "ERROR: the public manifest validator checks direct version publication; "
            "integrated archive-import manifests are validated by the archive-import API.",
            file=sys.stderr,
        )
        return 2

    if args.release and not args.server_url and args.flow != "archive-import":
        print("ERROR: --release requires --server-url so the committed Core validator checks publication semantics.", file=sys.stderr)
        return 2

    if args.server_url:
        token = os.environ.get("GALENE_CONTROLPLANE_TOKEN", "")
        version = args.version or ""
        package_slug = args.package_slug or manifest.get("app", {}).get("slug", "")
        if not token:
            print("ERROR: set GALENE_CONTROLPLANE_TOKEN from the approved secret manager/environment.", file=sys.stderr)
            return 2
        if not version or not package_slug:
            print("ERROR: --server-url requires --version and a manifest app.slug or --package-slug.", file=sys.stderr)
            return 2
        try:
            result = server_validate(args.server_url, token, package_slug, version, manifest)
        except (ValueError, RuntimeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        if result["valid"]:
            print("OK: offline checks and committed Core server validation passed.")
            return 0
        for error in result["errors"]:
            if isinstance(error, dict):
                path = error.get("path", "")
                message = error.get("message", "invalid manifest")
                kind = error.get("type", "")
                prefix = f"{path}: " if path else ""
                suffix = f" [{kind}]" if kind else ""
                print(f"ERROR: {prefix}{message}{suffix}", file=sys.stderr)
        return 1

    print("OK: manifest passes the pinned offline contract checks.")
    print("Server-side validation was not requested; publication remains authoritative.")
    if args.release and args.flow == "archive-import":
        print("The integrated archive-import API validates the selected internal registry source and imported image archives.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
