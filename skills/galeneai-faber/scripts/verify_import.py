#!/usr/bin/env python3
"""Verify a saved public archive-import response before installation; no writes or network."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from _support import load_json, validate_manifest


def verify_import(manifest: dict, status: dict, expected_images: dict, platform: str | None = None) -> dict:
    errors = validate_manifest(manifest, flow="archive-import")
    if errors:
        raise ValueError("Manifest fails the pinned archive-import contract")
    names = {item["name"] for item in manifest["components"] if "archive_import" in item}
    if not names or set(expected_images) != names:
        raise ValueError("Expected image references must cover every imported component exactly once")
    if not isinstance(status, dict) or status.get("status") != "ready" or not status.get("result_version_id"):
        raise ValueError("Import is not ready with a published version; installation must wait")
    returned_names = status.get("component_names")
    if not isinstance(returned_names, list) or len(returned_names) != len(names) or set(returned_names) != names:
        raise ValueError("Import component names do not match the manifest")
    mappings, digests = status.get("component_mappings"), status.get("component_digests")
    if not isinstance(mappings, dict) or not isinstance(digests, dict) or set(mappings) != names or set(digests) != names:
        raise ValueError("Every imported component needs a selected candidate and immutable digest")
    candidates = status.get("candidate_images", [])
    if not isinstance(candidates, list) or any(not isinstance(c, dict) or not c.get("id") for c in candidates):
        raise ValueError("Inspected candidate metadata is missing or invalid")
    by_id = {c["id"]: c for c in candidates}
    if len(by_id) != len(candidates):
        raise ValueError("Inspected candidate IDs are ambiguous")
    verified = {}
    for name in sorted(names):
        selected = by_id.get(mappings[name])
        expected = expected_images[name]
        if not isinstance(expected, str) or not expected:
            raise ValueError("Expected image references must be non-empty strings")
        if not selected or str(selected.get("reference", "")).removeprefix("docker.io/library/") != expected.removeprefix("docker.io/library/"):
            raise ValueError(f"Selected candidate does not match the intended image for component {name}")
        if not isinstance(digests[name], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digests[name]):
            raise ValueError(f"Component {name} has no valid immutable SHA-256 digest")
        if platform and not any(f"{p.get('os')}/{p.get('architecture')}" == platform for p in selected.get("platforms", []) if isinstance(p, dict)):
            raise ValueError(f"Component {name} does not include the requested platform")
        verified[name] = {"candidate_id": selected["id"], "digest": digests[name]}
    return {"import_status": "ready", "version_id": status["result_version_id"], "components": verified,
            "platform_checked": platform, "deployment_verified": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True, help="Saved response from the public import status endpoint")
    parser.add_argument("--expected-images", type=Path, required=True, help="JSON object mapping imported component names to intended image references")
    parser.add_argument("--platform", help="Required image platform, for example linux/amd64")
    args = parser.parse_args()
    try:
        result = verify_import(load_json(args.manifest), load_json(args.status), load_json(args.expected_images), args.platform)
    except (ValueError, RuntimeError, TypeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    # Never echo the API response: it may include staging URLs or private metadata.
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
