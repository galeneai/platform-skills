"""Resolve public Galene runtime config and download the target OpenAPI; no auth."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request

from http_client import open_no_redirect


def https_base(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("Expected an HTTPS base URL without credentials, query or fragment")
    # Trigger validation of malformed ports.
    parsed.port
    return value.rstrip("/")


def fetch_json(url: str) -> dict:
    request = Request(url, headers={"Accept": "application/json"})
    with open_no_redirect(request, timeout=20) as response:
        payload = response.read(16 * 1024 * 1024 + 1)
    if len(payload) > 16 * 1024 * 1024:
        raise ValueError("Public JSON document exceeds 16 MiB")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    return data


def discover(*, ui_url: str | None = None, api_base_url: str | None = None) -> dict:
    if bool(ui_url) == bool(api_base_url):
        raise ValueError("Supply exactly one UI URL or explicit Core API base")
    tenant_slug = None
    if ui_url:
        parsed = urlsplit(ui_url)
        # Never request a callback query, and never forward credentials.
        origin = https_base(urlunsplit((parsed.scheme, parsed.netloc, "", "", "")))
        config = fetch_json(origin + "/galene-config")
        api_base_url = config.get("GALENE_PUBLIC_API_BASE_URL")
        if not isinstance(api_base_url, str) or not api_base_url:
            raise ValueError("Runtime config has no Core API base; supply --api-base-url")
        tenant_slug = config.get("GALENE_PUBLIC_TENANT_SLUG") or config.get("tenant_slug")
        if tenant_slug is not None and not isinstance(tenant_slug, str):
            raise ValueError("Invalid public tenant slug")
    base = https_base(api_base_url)
    schema_url = base + "/openapi.json"
    spec = fetch_json(schema_url)
    if not isinstance(spec.get("openapi"), str) or not spec["openapi"].startswith("3."):
        raise ValueError("Target document is not an OpenAPI 3 schema")
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("Target OpenAPI has no paths object")
    # Reject a common mistake: an app-local schema at a BFF origin.
    if not any(path.startswith(("/public/tenants/", "/controlplane/")) for path in paths):
        raise ValueError("Schema has no Galene tenant/Control Plane operations; verify Core API base")
    return {"api_base_url": base, "openapi_url": schema_url,
            "tenant_slug": tenant_slug, "spec": spec}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="Tenant Console, Control Plane or app UI URL")
    source.add_argument("--api-base-url", help="Explicit public Core API base")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = discover(ui_url=args.url, api_base_url=args.api_base_url)
        args.output.write_text(json.dumps(result.pop("spec"), indent=2) + "\n", encoding="utf-8")
    except Exception:
        # Network exceptions can contain URLs; do not echo config, callback or response data.
        parser.exit(1, "Discovery failed: check the public runtime config, Core API URL, TLS and OpenAPI contract.\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
