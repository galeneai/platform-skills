"""Focused tests for the skill's stack-free developer tools; run only when asked."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import tarfile
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from shutil import copyfile
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
EXAMPLES = SKILL_ROOT / "references" / "contracts" / "examples"
sys.path.insert(0, str(SCRIPTS))

from _support import load_json, validate_manifest  # noqa: E402
from doctor import doctor as run_doctor  # noqa: E402
from http_client import NoRedirectHandler, open_no_redirect  # noqa: E402
from install import (  # noqa: E402
    _load_service_bindings,
    install_deployment,
    request_json,
    verify_service_target,
)
from install import main as install_main  # noqa: E402


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


PACKAGE = load_script("package")
VALIDATE = load_script("validate")


def service_target_contract(version="1.3.0"):
    """Public target fixture with the manifest and installation contract's real fields."""
    schemas = {
        "ApplicationManifest": {"properties": {
            "service_requirements": {"type": "array", "items": {"$ref": "#/components/schemas/ApplicationServiceRequirement"}},
            "resource_requirements": {"type": "array", "items": {"$ref": "#/components/schemas/ApplicationResourceRequirement"}},
        }},
        "ApplicationServiceRequirement": {"properties": {
            "role": {"type": "string"}, "service": {"type": "string"},
            "operations": {"type": "array", "items": {"type": "string"}},
            "resource_roles": {"type": "array", "items": {"type": "string"}},
            "execution_modes": {"type": "array", "items": {"type": "string"}},
        }},
        "ApplicationResourceRequirement": {"properties": {
            field: {"type": "string"} for field in ("role", "kind", "access")
        }},
        "CreateTenantApplicationDeploymentRequest": {"properties": {
            "approved_services": {"type": "array", "items": {"type": "string"}},
            "service_bindings": {"type": "object", "additionalProperties": {"$ref": "#/components/schemas/ApplicationServiceBinding"}},
        }},
        "ApplicationServiceBinding": {"additionalProperties": False, "properties": {
            "resource_id": {"type": "string", "format": "uuid"},
            "access": {"type": "string", "enum": ["read", "read_write"]},
        }},
    }
    install = {"post": {"requestBody": {"content": {"application/json": {
        "schema": {"$ref": "#/components/schemas/CreateTenantApplicationDeploymentRequest"}
    }}}}}
    return {
        "openapi": "3.1.0", "info": {"version": version}, "components": {"schemas": schemas},
        "paths": {
            "/v1/services/token": {"post": {}},
            "/v1/services/grants": {"get": {}},
            "/v1/services/operations": {"post": {}, "get": {}},
            "/v1/services/operations/{operation_id}": {"get": {}},
            "/v1/services/operations/{operation_id}/cancel": {"post": {}},
            "/v1/services/operations/{operation_id}/artifacts/{name}": {"get": {}},
            "/tenant/applications/deployments": install,
            "/controlplane/tenants/{tenant_id}/application-deployments": install,
        },
    }


class SkillToolingTests(unittest.TestCase):
    def test_public_manifest_example_passes_offline_contract(self):
        manifest = load_json(EXAMPLES / "team-notes-manifest.json")
        self.assertEqual(validate_manifest(manifest), [])

    def test_new_version_rejects_legacy_capability_and_outbound_hosts(self):
        manifest = load_json(EXAMPLES / "team-notes-manifest.json")
        manifest["capabilities"].append({"name": "direct_tenant_db"})
        manifest["components"][0]["connectivity"] = {"outbound_hosts": ["example.com"]}
        errors = validate_manifest(manifest)
        self.assertTrue(any("capabilities" in error for error in errors))
        self.assertTrue(any("connectivity" in error for error in errors))

    def test_doctor_uses_integrated_import_flow_from_project_context(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            manifest = load_json(EXAMPLES / "multi-component-archive-import-manifest.json")
            context = load_json(EXAMPLES / "app-project.json")
            context["registry"] = {"choice": "integrated"}
            (project / "galene-app.json").write_text(json.dumps(manifest), encoding="utf-8")
            (project / "galene-app-project.json").write_text(json.dumps(context), encoding="utf-8")

            self.assertEqual(run_doctor(project), [])

    def test_release_check_requires_immutable_image_digests(self):
        manifest = load_json(EXAMPLES / "team-notes-manifest.json")
        manifest["components"][0]["image_source"]["reference"] = "latest"
        errors = validate_manifest(manifest, require_digests=True)
        self.assertTrue(any("sha256 digest" in error for error in errors))

    def test_package_bundle_is_deterministic_and_excludes_local_context_and_secrets(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            copyfile(EXAMPLES / "team-notes-manifest.json", project / "galene-app.json")
            copyfile(EXAMPLES / "app-project.json", project / "galene-app-project.json")
            copyfile(EXAMPLES / "compatibility.json", project / "compatibility.json")
            (project / "release-notes.md").write_text("First stable release.\n", encoding="utf-8")
            (project / ".env").write_text("PASSWORD=never-include\n", encoding="utf-8")
            first = PACKAGE.build_bundle(project, "1.2.0", project / "one.tar.gz")
            second = PACKAGE.build_bundle(project, "1.2.0", project / "two.tar.gz")
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with tarfile.open(first, "r:gz") as archive:
                names = set(archive.getnames())
            self.assertEqual(names, {"manifest.json", "compatibility.json", "release-metadata.json", "release-notes.md"})
            self.assertNotIn("galene-app-project.json", names)
            self.assertNotIn(".env", names)

    def test_package_requires_compatibility_to_match_pinned_core_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            copyfile(EXAMPLES / "team-notes-manifest.json", project / "galene-app.json")
            copyfile(EXAMPLES / "app-project.json", project / "galene-app-project.json")
            compatibility = load_json(EXAMPLES / "compatibility.json")
            compatibility["openapi_sha256"] = "0" * 64
            (project / "compatibility.json").write_text(json.dumps(compatibility), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pinned contract snapshot"):
                PACKAGE.build_bundle(project, "1.2.0", project / "bundle.tar.gz")

    def test_package_rejects_compatibility_from_an_arbitrary_core_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            copyfile(EXAMPLES / "team-notes-manifest.json", project / "galene-app.json")
            copyfile(EXAMPLES / "app-project.json", project / "galene-app-project.json")
            compatibility = load_json(EXAMPLES / "compatibility.json")
            compatibility["platform_core_commit"] = "0" * 40
            (project / "compatibility.json").write_text(json.dumps(compatibility), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pinned contract snapshot"):
                PACKAGE.build_bundle(project, "1.2.0", project / "bundle.tar.gz")

    def test_integrated_mode_packages_multiple_archive_import_components(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            manifest = load_json(EXAMPLES / "team-notes-manifest.json")
            registry_source_id = "66666666-6666-4666-8666-666666666666"
            for component in manifest["components"]:
                component.pop("image_source")
                component["archive_import"] = {"registry_source_id": registry_source_id}
            (project / "galene-app.json").write_text(json.dumps(manifest), encoding="utf-8")
            context = load_json(EXAMPLES / "app-project.json")
            context["registry"]["choice"] = "integrated"
            context["registry"].pop("source_slug", None)
            (project / "galene-app-project.json").write_text(json.dumps(context), encoding="utf-8")
            compatibility = load_json(EXAMPLES / "compatibility.json")
            compatibility["registry_mode"] = "integrated"
            (project / "compatibility.json").write_text(json.dumps(compatibility), encoding="utf-8")
            bundle = PACKAGE.build_bundle(project, "1.2.0", project / "bundle.tar.gz")
            with tarfile.open(bundle, "r:gz") as archive:
                packaged_manifest = json.load(archive.extractfile("manifest.json"))
            self.assertEqual(len(packaged_manifest["components"]), 2)
            self.assertTrue(all("archive_import" in item for item in packaged_manifest["components"]))

    def test_integrated_import_components_must_share_one_registry_source(self):
        manifest = load_json(EXAMPLES / "team-notes-manifest.json")
        for index, component in enumerate(manifest["components"]):
            component.pop("image_source")
            component["archive_import"] = {
                "registry_source_id": f"{index + 1}1111111-1111-4111-8111-111111111111"
            }
        errors = validate_manifest(manifest, flow="archive-import")
        self.assertTrue(any("same registry_source_id" in error for error in errors))

    def test_tenant_install_requires_exact_tenant_and_available_version(self):
        calls = []

        def fake_api(base, path, token, method, payload):
            calls.append((path, method, payload))
            if method == "GET":
                return {
                    "success": True,
                    "result": [{
                        "package": {"id": "package-1", "slug": "team-notes"},
                        "version": {"id": "version-1", "version": "1.2.0"}
                    }]
                }
            return {"success": True, "result": {"id": "deployment-1", "status": "pending"}}

        with self.assertRaisesRegex(ValueError, "does not match"):
            install_deployment(
                base_url="https://tenant.example",
                tenant="acme-prod",
                project_tenant="acme-test",
                package_id="package-1",
                version_id="version-1",
                slug="team-notes",
                app_version="1.2.0",
                token="test-only-token",
                api_request=fake_api,
            )
        self.assertEqual(calls, [])

        result = install_deployment(
            base_url="https://tenant.example",
            tenant="acme-test",
            project_tenant="acme-test",
            package_id="package-1",
            version_id="version-1",
            slug="team-notes",
            app_version="1.2.0",
            token="test-only-token",
            api_request=fake_api,
        )
        self.assertEqual(result["id"], "deployment-1")
        self.assertEqual(calls[-1][1], "POST")
        self.assertEqual(calls[-1][2], {"package_id": "package-1", "version_id": "version-1"})

    def test_publisher_install_resolves_tenant_and_exact_release_ids(self):
        tenant_id = "11111111-1111-4111-8111-111111111111"
        package_id = "22222222-2222-4222-8222-222222222222"
        version_id = "33333333-3333-4333-8333-333333333333"
        calls = []

        def fake_api(base, path, token, method, payload):
            calls.append((path, method, payload))
            if path == "/controlplane/tenants":
                return {"success": True, "result": [{"id": tenant_id, "slug": "acme-test"}]}
            if path == "/controlplane/applications":
                return {"success": True, "result": [{"id": package_id, "slug": "team-notes"}]}
            if path.endswith("/versions"):
                return {"success": True, "result": [{"id": version_id, "version": "1.2.0"}]}
            return {"success": True, "result": {"id": "deployment-1", "status": "pending"}}

        result = install_deployment(
            base_url="https://control-plane.example",
            tenant="acme-test",
            project_tenant="acme-test",
            package_id=package_id,
            version_id=version_id,
            slug="team-notes",
            app_version="1.2.0",
            token="test-only-token",
            auth_context="publisher",
            api_request=fake_api,
        )
        self.assertEqual(result["id"], "deployment-1")
        self.assertEqual(calls[-1][0], f"/controlplane/tenants/{tenant_id}/application-deployments")
        self.assertEqual(calls[-1][2], {"package_id": package_id, "version_id": version_id})

    def test_publisher_install_uses_tenant_domain_options_then_binds_required_route(self):
        tenant_id = "11111111-1111-4111-8111-111111111111"
        package_id = "22222222-2222-4222-8222-222222222222"
        version_id = "33333333-3333-4333-8333-333333333333"
        domain_id = "44444444-4444-4444-8444-444444444444"
        deployment_id = "55555555-5555-4555-8555-555555555555"
        calls = []

        def fake_api(base, path, token, method, payload):
            calls.append((path, method, payload))
            if path == "/controlplane/tenants":
                return {"success": True, "result": [{"id": tenant_id, "slug": "acme-test"}]}
            if path == "/controlplane/applications":
                return {"success": True, "result": [{"id": package_id, "slug": "team-notes"}]}
            if path.endswith("/versions"):
                return {"success": True, "result": [{"id": version_id, "version": "1.2.0"}]}
            if path.endswith("/application-domain-options"):
                return {"success": True, "result": [{"id": domain_id, "host": "apps.example.test", "display_name": "Apps"}]}
            if method == "POST" and path == f"/controlplane/tenants/{tenant_id}/application-deployments":
                return {"success": True, "result": {"id": deployment_id, "status": "pending"}}
            if method == "POST" and path == f"/controlplane/application-deployments/{deployment_id}/domains":
                return {"success": True, "result": {"id": "binding-1", "host": "apps.example.test"}}
            raise AssertionError(f"unexpected API call: {method} {path}")

        result = install_deployment(
            base_url="https://control-plane.example",
            tenant="acme-test",
            project_tenant="acme-test",
            package_id=package_id,
            version_id=version_id,
            slug="team-notes",
            app_version="1.2.0",
            token="test-only-token",
            auth_context="publisher",
            routes=[{"component": "web", "role": "frontend", "host_required": True}],
            domain_bindings={("web", "frontend"): domain_id},
            api_request=fake_api,
        )

        self.assertEqual(result["id"], deployment_id)
        self.assertEqual(result["domain_bindings"][0]["host"], "apps.example.test")
        self.assertIn(
            (
                f"/controlplane/application-deployments/{deployment_id}/domains",
                "POST",
                {
                    "component_name": "web",
                    "route_role": "frontend",
                    "managed_domain_id": domain_id,
                },
            ),
            calls,
        )

    def test_publisher_install_requires_domain_choice_before_creating_deployment(self):
        tenant_id = "11111111-1111-4111-8111-111111111111"
        package_id = "22222222-2222-4222-8222-222222222222"
        version_id = "33333333-3333-4333-8333-333333333333"
        calls = []

        def fake_api(base, path, token, method, payload):
            calls.append((path, method, payload))
            if path == "/controlplane/tenants":
                return {"success": True, "result": [{"id": tenant_id, "slug": "acme-test"}]}
            if path == "/controlplane/applications":
                return {"success": True, "result": [{"id": package_id, "slug": "team-notes"}]}
            if path.endswith("/versions"):
                return {"success": True, "result": [{"id": version_id, "version": "1.2.0"}]}
            if path.endswith("/application-domain-options"):
                return {"success": True, "result": [{"id": "44444444-4444-4444-8444-444444444444", "host": "apps.example.test"}]}
            raise AssertionError(f"deployment must not be created without a domain choice: {method} {path}")

        with self.assertRaisesRegex(ValueError, "select a domain"):
            install_deployment(
                base_url="https://control-plane.example",
                tenant="acme-test",
                project_tenant="acme-test",
                package_id=package_id,
                version_id=version_id,
                slug="team-notes",
                app_version="1.2.0",
                token="test-only-token",
                auth_context="publisher",
                routes=[{"component": "web", "role": "frontend", "host_required": True}],
                api_request=fake_api,
            )
        self.assertFalse(any(method == "POST" for _, method, _ in calls))

    def test_service_install_forwards_explicit_selections_in_both_auth_flows(self):
        tenant_id = "11111111-1111-4111-8111-111111111111"
        package_id = "22222222-2222-4222-8222-222222222222"
        version_id = "33333333-3333-4333-8333-333333333333"
        resource_id = "44444444-4444-4444-8444-444444444444"
        manifest = {
            "service_requirements": [{"role": "files", "required": True, "resource_roles": ["workspace"]},
                                     {"role": "optional_search", "resource_roles": []}],
            "resource_requirements": [{"role": "workspace", "kind": "filesystem", "access": "read_write", "required": True}],
        }
        bindings = {"workspace": {"resource_id": resource_id, "access": "read_write"}}
        for auth_context in ("tenant", "publisher"):
            with self.subTest(auth_context=auth_context):
                calls = []

                def fake_api(base, path, token, method, payload, calls=calls):
                    calls.append((path, method, payload))
                    if path == "/openapi.json":
                        self.assertEqual(token, "")
                        return service_target_contract()
                    if path == "/controlplane/tenants":
                        return {"result": [{"id": tenant_id, "slug": "acme-test"}]}
                    if path == "/controlplane/applications":
                        return {"result": [{"id": package_id, "slug": "team-notes"}]}
                    if path.endswith("/versions"):
                        return {"result": [{"id": version_id, "version": "1.2.0"}]}
                    if path == "/tenant/applications/available":
                        return {"result": [{"package": {"id": package_id, "slug": "team-notes"},
                                            "version": {"id": version_id, "version": "1.2.0"}}]}
                    return {"result": {"id": "deployment-1", "status": "pending"}}

                install_deployment(base_url="https://core.example", tenant="acme-test", project_tenant="acme-test",
                    package_id=package_id, version_id=version_id, slug="team-notes", app_version="1.2.0",
                    token="test-only-token", auth_context=auth_context, manifest=manifest,
                    approved_services=["files"], service_bindings=bindings, api_request=fake_api)
                expected_path = "/tenant/applications/deployments" if auth_context == "tenant" else f"/controlplane/tenants/{tenant_id}/application-deployments"
                self.assertEqual(calls[-1], (expected_path, "POST", {
                    "package_id": package_id, "version_id": version_id,
                    "approved_services": ["files"], "service_bindings": bindings,
                }))

    def test_service_install_rejects_old_or_unknown_target_before_authenticated_calls(self):
        manifest = {"service_requirements": [{"role": "search"}]}
        for auth_context in ("tenant", "publisher"):
            for version in ("1.2.0", "1.2.99", "2.0.0", "unknown", "1.3.0rc1"):
                with self.subTest(auth_context=auth_context, version=version):
                    calls = []

                    def api(base, path, token, method, payload, calls=calls, version=version):
                        calls.append((path, token, method))
                        return service_target_contract(version)

                    with self.assertRaisesRegex(RuntimeError, "verified Core"):
                        install_deployment(
                            base_url="https://core.example", tenant="acme-test", project_tenant="acme-test",
                            package_id="package-1", version_id="version-1", slug="team-notes",
                            app_version="1.0.0", token="test-only-secret", auth_context=auth_context,
                            manifest=manifest, api_request=api,
                        )
                    self.assertEqual(calls, [("/openapi.json", "", "GET")])

    def test_service_target_rejects_missing_contract_and_invalid_refs(self):
        for missing in ("manifest_fields", "field_type", "binding_fields", "binding_authority", "route", "external_ref", "cycle", "bad_components"):
            with self.subTest(missing=missing):
                target = service_target_contract()
                schemas = target["components"]["schemas"]
                if missing == "manifest_fields":
                    del schemas["ApplicationManifest"]["properties"]["service_requirements"]
                elif missing == "field_type":
                    schemas["ApplicationResourceRequirement"]["properties"]["kind"] = {"type": "integer"}
                elif missing == "binding_fields":
                    del schemas["ApplicationServiceBinding"]["properties"]["access"]
                elif missing == "binding_authority":
                    schemas["ApplicationServiceBinding"]["properties"]["mcp_tools"] = {"type": "object"}
                elif missing == "route":
                    del target["paths"]["/v1/services/operations/{operation_id}/cancel"]
                elif missing == "external_ref":
                    schemas["ApplicationServiceBinding"] = {"$ref": "https://untrusted.example/schema"}
                elif missing == "cycle":
                    schemas["ApplicationServiceBinding"] = {"$ref": "#/components/schemas/ApplicationServiceBinding"}
                else:
                    target["components"] = []
                for auth_context in ("tenant", "publisher"):
                    with self.subTest(auth_context=auth_context), patch("install.request_json", return_value=target) as api:
                        with self.assertRaises(RuntimeError):
                            install_deployment(
                                base_url="https://core.example", tenant="acme-test", project_tenant="acme-test",
                                package_id="package-1", version_id="version-1", slug="team-notes",
                                app_version="1.0.0", token="test-only-secret", auth_context=auth_context,
                                manifest={"resource_requirements": [{"role": "workspace"}]}, api_request=api,
                            )
                    api.assert_called_once_with("https://core.example", "/openapi.json", "", "GET", None)

    def test_empty_requirements_preserve_legacy_target_flow(self):
        with patch("install.request_json") as api:
            verify_service_target("https://core.example", {"service_requirements": [], "resource_requirements": []})
            verify_service_target("https://core.example", None)
        api.assert_not_called()

    def test_public_target_request_does_not_send_authorization(self):
        with patch("install.open_no_redirect") as opener:
            opener.return_value.__enter__.return_value.read.return_value = b"{}"
            request_json("https://core.example", "/openapi.json", "")
        request = opener.call_args.args[0]
        self.assertIsNone(request.get_header("Authorization"))
        self.assertEqual(opener.call_args.kwargs["timeout"], 30)

    def test_publication_preflight_rejects_old_target_before_validation_post(self):
        with patch("install.request_json", return_value=service_target_contract("1.2.0")), \
             patch.object(VALIDATE, "open_no_redirect") as validator:
            with self.assertRaisesRegex(RuntimeError, "verified Core"):
                VALIDATE.server_validate("https://core.example", "test-only-secret", "team-notes", "1.0.0",
                                         {"service_requirements": [{"role": "search"}]})
        validator.assert_not_called()

    def test_new_target_keeps_full_requires_core_validation_on_server(self):
        errors = {"valid": False, "errors": [{
            "path": "manifest.app.requires_core", "message": "incompatible Core", "type": "value_error"
        }]}
        response = urllib.error.HTTPError(
            "https://core.example/controlplane/application-manifests/validate", 422,
            "invalid manifest", None, io.BytesIO(json.dumps(errors).encode()),
        )
        manifest = {"app": {"requires_core": ">=1.5,<2.0"}, "service_requirements": [{"role": "search"}]}
        with patch("install.request_json", return_value=service_target_contract()) as target, \
             patch.object(VALIDATE, "open_no_redirect", side_effect=response) as validator:
            result = VALIDATE.server_validate("https://core.example", "test-only-secret", "team-notes", "1.0.0", manifest)
        self.assertFalse(result["valid"])
        target.assert_called_once_with("https://core.example", "/openapi.json", "", "GET", None)
        request = validator.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(json.loads(request.data)["manifest"], manifest)
        self.assertTrue(request.full_url.endswith("/application-manifests/validate"))

    def test_archive_target_gate_is_public_and_does_not_call_direct_validator(self):
        manifest = load_json(EXAMPLES / "multi-component-archive-import-manifest.json")
        manifest["app"]["requires_core"] = ">=1.3,<2.0"
        manifest["service_requirements"] = [{"role": "web_fetch", "service": "web", "operations": ["fetch"]}]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "galene-app.json"
            path.write_text(json.dumps(manifest))
            for version, expected in (("1.2.0", 2), ("1.3.0", 0)):
                with self.subTest(version=version), \
                     patch("sys.argv", ["validate.py", str(path), "--flow", "archive-import", "--target-url", "https://core.example"]), \
                     patch("install.request_json", return_value=service_target_contract(version)) as target, \
                     patch.object(VALIDATE, "open_no_redirect") as validator, \
                     patch("sys.stdout", new_callable=io.StringIO), patch("sys.stderr", new_callable=io.StringIO):
                    self.assertEqual(VALIDATE.main(), expected)
                target.assert_called_once_with("https://core.example", "/openapi.json", "", "GET", None)
                validator.assert_not_called()

    def test_service_install_rejects_invalid_authority_before_any_http(self):
        resource_id = "44444444-4444-4444-8444-444444444444"
        manifest = {
            "service_requirements": [{"role": "files", "required": True, "resource_roles": ["workspace"]}],
            "resource_requirements": [{"role": "workspace", "kind": "filesystem", "access": "read"}],
        }
        binding = {"resource_id": resource_id, "access": "read"}
        cases = [
            (None, {"workspace": binding}),
            (["foreign"], {"workspace": binding}),
            (["Files"], {"workspace": binding}),
            (["files", "files"], {"workspace": binding}),
            (["files"], {}),
            (["files"], {"foreign": binding}),
            (["files"], {"workspace": {**binding, "resource_id": "not-a-uuid"}}),
            (["files"], {"workspace": {**binding, "access": "admin"}}),
            (["files"], {"workspace": {**binding, "access": "read_write"}}),
            (["files"], {"workspace": {**binding, "mcp_tools": {"tool": "sha256:forged"}}}),
            (["files"], {"workspace": {**binding, "tenant_id": resource_id}}),
        ]
        for approved, bindings in cases:
            with self.subTest(approved=approved, bindings=bindings), patch("install.request_json") as api:
                with self.assertRaises(ValueError):
                    install_deployment(base_url="https://core.example", tenant="acme-test", project_tenant="acme-test",
                        package_id="package-1", version_id="version-1", slug="team-notes", app_version="1.2.0",
                        token="test-only-token", manifest=manifest, approved_services=approved,
                        service_bindings=bindings, api_request=api)
                api.assert_not_called()
        with patch("install.request_json") as api, self.assertRaisesRegex(ValueError, "require the manifest"):
            install_deployment(base_url="https://core.example", tenant="acme-test", project_tenant="acme-test",
                package_id="package-1", version_id="version-1", slug="team-notes", app_version="1.2.0",
                token="test-only-token", approved_services=["files"], api_request=api)
        api.assert_not_called()

    def test_service_binding_file_rejects_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bindings.json"
            path.write_text('{"workspace":{"resource_id":"first","resource_id":"second","access":"read"}}')
            with self.assertRaisesRegex(ValueError, "duplicate keys"):
                _load_service_bindings(path)

    def test_install_cli_reads_repeated_service_roles_and_binding_file(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            copyfile(EXAMPLES / "app-project.json", project / "galene-app-project.json")
            manifest = load_json(EXAMPLES / "team-notes-manifest.json")
            (project / "galene-app.json").write_text(json.dumps(manifest))
            bindings = {"workspace": {"resource_id": "44444444-4444-4444-8444-444444444444", "access": "read"}}
            path = project / "bindings.json"
            path.write_text(json.dumps(bindings))
            argv = ["install.py", "--project", str(project), "--base-url", "https://core.example",
                    "--tenant", "acme-test", "--app-version", "1.2.0", "--package-id", "package-1",
                    "--version-id", "version-1", "--approved-service", "files", "--approved-service", "search",
                    "--service-bindings", str(path)]
            with patch("sys.argv", argv), patch.dict("os.environ", {"GALENE_TENANT_TOKEN": "test-only-token"}), \
                 patch("install.install_deployment", return_value={"id": "deployment-1"}) as install, \
                 patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(install_main(), 0)
            self.assertEqual(install.call_args.kwargs["approved_services"], ["files", "search"])
            self.assertEqual(install.call_args.kwargs["service_bindings"], bindings)
            self.assertEqual(install.call_args.kwargs["manifest"], manifest)

    def test_server_manifest_validation_uses_public_request_and_error_shape(self):
        body = json.dumps({
            "valid": False,
            "errors": [{
                "path": "manifest.components[0].image_source.reference",
                "message": "invalid digest",
                "type": "value_error",
            }],
        }).encode()
        response = urllib.error.HTTPError(
            "https://control-plane.example/controlplane/application-manifests/validate",
            422,
            "invalid manifest",
            None,
            io.BytesIO(body),
        )
        with patch.object(VALIDATE, "open_no_redirect", side_effect=response) as urlopen:
            result = VALIDATE.server_validate(
                "https://control-plane.example",
                "test-only-token",
                "team-notes",
                "1.2.0",
                {"schema_version": "1.0"},
            )

        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/controlplane/application-manifests/validate"))
        self.assertEqual(
            json.loads(request.data),
            {"package_slug": "team-notes", "version": "1.2.0", "manifest": {"schema_version": "1.0"}},
        )
        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["path"], "manifest.components[0].image_source.reference")

    def test_api_http_opener_refuses_redirects(self):
        request = urllib.request.Request("https://control-plane.example/controlplane/tenants")
        redirect = urllib.error.HTTPError(
            request.full_url,
            302,
            "redirect",
            {"Location": "https://untrusted.example/collect"},
            io.BytesIO(b""),
        )
        with patch("http_client.urllib.request.build_opener") as build_opener:
            build_opener.return_value.open.side_effect = redirect
            with self.assertRaises(urllib.error.HTTPError):
                open_no_redirect(request)

        handlers = build_opener.call_args.args
        self.assertEqual(len(handlers), 1)
        self.assertIsInstance(handlers[0], NoRedirectHandler)
        build_opener.return_value.open.assert_called_once_with(request, timeout=30)

    def test_api_client_reports_redirect_without_following_it(self):
        redirect = urllib.error.HTTPError(
            "https://control-plane.example/controlplane/tenants",
            302,
            "redirect",
            {"Location": "https://untrusted.example/collect"},
            io.BytesIO(b""),
        )
        with patch("install.open_no_redirect", side_effect=redirect) as opener:
            with self.assertRaisesRegex(RuntimeError, "HTTP 302"):
                request_json(
                    "https://control-plane.example",
                    "/controlplane/tenants",
                    "test-only-token",
                )
        opener.assert_called_once()

    def test_snapshot_hashes_match_lock(self):
        lock = load_json(SKILL_ROOT / "references" / "contracts" / "snapshot-lock.json")
        schema = SKILL_ROOT / "references" / "contracts" / "application-manifest.schema.json"
        openapi = SKILL_ROOT / "references" / "contracts" / "application-api.openapi.yaml"
        self.assertEqual(
            hashlib.sha256(schema.read_bytes()).hexdigest(),
            lock["contracts"]["application_manifest_json_schema"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(openapi.read_bytes()).hexdigest(),
            lock["contracts"]["app_api_openapi"]["sha256"],
        )


if __name__ == "__main__":
    unittest.main()
