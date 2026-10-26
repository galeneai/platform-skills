"""Inference authoring and target checks, without a running Core or provider."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from _support import validate_manifest  # noqa: E402
from install import verify_service_target  # noqa: E402
from test_tooling import EXAMPLES, load_json, service_target_contract  # noqa: E402


def inference_target(version="2.2.0"):
    target = service_target_contract(version)
    schemas = target["components"]["schemas"]
    schemas["ApplicationServiceRequirement"]["properties"]["operations"]["items"]["enum"] = [
        "chat", "embedding", "transcribe", "speak", "decide", "realtime",
    ]
    schemas["ApplicationManifest"]["properties"]["model_requirements"] = {
        "anyOf": [{"type": "array", "items": {"$ref": "#/components/schemas/ApplicationModelRequirement"}}, {"type": "null"}],
    }
    schemas["ApplicationModelRequirement"] = {"properties": {
        "slot": {"type": "string", "enum": ["llm", "embedding", "stt", "tts", "classification", "realtime"]},
        "capabilities": {"type": "array", "items": {"type": "string", "enum": ["chat", "embedding", "transcription", "tts", "systemone", "realtime", "function_calling"]}},
        "input_modalities": {"type": "array", "items": {"type": "string", "enum": ["text", "image", "audio"]}},
        "min_context_window": {"anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}]},
    }}
    target["paths"]["/v1/services/inference/{service_role}/speak"] = {"post": {
        "requestBody": {"content": {"application/json": {"schema": {
            "additionalProperties": False,
            "properties": {"model_role": {"type": "string"}, "input": {"type": "string"}},
        }}}},
    }}
    return target


class InferenceContractTests(unittest.TestCase):
    def verify(self, manifest, target):
        verify_service_target("https://core.example", manifest, api_request=lambda *args: target)

    def test_existing_service_contract_works_on_qualified_core_1_and_2(self):
        for version in ("1.3.0", "1.4.0", "2.0.0", "2.2.0"):
            with self.subTest(version=version):
                self.verify({"service_requirements": [{"role": "files"}]}, service_target_contract(version))

    def test_native_roles_and_services_pass_offline_authoring(self):
        manifest = load_json(EXAMPLES / "team-notes-manifest.json")
        manifest["model_requirements"] = [
            {"role": "voice", "slot": "tts", "capabilities": ["tts"], "input_modalities": ["text"]},
            {"role": "judge", "slot": "classification", "capabilities": ["systemone"], "input_modalities": ["text"]},
            {"role": "conversation", "slot": "realtime", "capabilities": ["realtime"], "input_modalities": ["audio"]},
            {"role": "writer", "slot": "llm", "min_context_window": 32768},
        ]
        manifest["service_requirements"] = [{"role": "reasoning", "service": "inference", "operations": ["speak", "decide", "realtime"]}]
        self.assertEqual(validate_manifest(manifest), [])
        manifest["model_requirements"][3]["min_context_window"] = 0
        self.assertTrue(validate_manifest(manifest))

    def test_requested_inference_operation_must_be_in_target_catalog(self):
        target = inference_target("1.3.0")
        target["components"]["schemas"]["ApplicationServiceRequirement"]["properties"]["operations"]["items"]["enum"].remove("decide")
        with self.assertRaises(RuntimeError):
            self.verify({"service_requirements": [{"role": "judge", "service": "inference", "operations": ["decide"]}]}, target)

    def test_requested_model_contract_is_checked_even_without_service_requirements(self):
        manifest = {"model_requirements": [{"role": "voice", "slot": "tts", "capabilities": ["tts"], "input_modalities": ["text"]}]}
        self.verify(manifest, inference_target())
        for field in ("slot", "capabilities", "input_modalities"):
            target = inference_target("1.3.0")
            schema = target["components"]["schemas"]["ApplicationModelRequirement"]["properties"][field]
            (schema if field == "slot" else schema["items"])["enum"] = []
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                self.verify(manifest, target)

    def test_declared_context_requirement_needs_target_support(self):
        manifest = {"model_requirements": [{"role": "writer", "slot": "llm", "min_context_window": 32768}]}
        self.verify(manifest, inference_target())
        target = inference_target("1.3.0")
        del target["components"]["schemas"]["ApplicationModelRequirement"]["properties"]["min_context_window"]
        with self.assertRaises(RuntimeError):
            self.verify(manifest, target)

    def test_declared_context_minimum_must_fit_target_numeric_bounds(self):
        manifest = {"model_requirements": [{"role": "writer", "slot": "llm", "min_context_window": 32768}]}
        for bounds, accepted in (
            ({"minimum": 1, "maximum": 1024}, False),
            ({"minimum": 65536}, False),
            ({"minimum": 32768, "maximum": 32768}, True),
            ({"exclusiveMinimum": 32768}, False),
            ({"exclusiveMaximum": 32768}, False),
            ({}, True),
        ):
            target = inference_target()
            target["components"]["schemas"]["ApplicationModelRequirement"]["properties"]["min_context_window"]["anyOf"][0] = {"type": "integer", **bounds}
            with self.subTest(bounds=bounds):
                if accepted:
                    self.verify(manifest, target)
                else:
                    with self.assertRaises(RuntimeError):
                        self.verify(manifest, target)

    def test_invalid_target_context_bound_has_sanitized_contract_failure(self):
        manifest = {"model_requirements": [{"role": "writer", "slot": "llm", "min_context_window": 32768}]}
        for name in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"):
            for value in ("not-a-number", float("nan"), float("inf"), float("-inf")):
                target = inference_target()
                target["components"]["schemas"]["ApplicationModelRequirement"]["properties"]["min_context_window"]["anyOf"][0][name] = value
                with self.subTest(name=name, value=value), self.assertRaises(RuntimeError):
                    self.verify(manifest, target)

    def test_speech_requires_typed_live_route_not_only_operation_name(self):
        manifest = {"service_requirements": [{"role": "voice", "service": "inference", "operations": ["speak"]}]}
        self.verify(manifest, inference_target())
        for missing in ("route", "model_role"):
            target = inference_target("1.3.0")
            if missing == "route":
                del target["paths"]["/v1/services/inference/{service_role}/speak"]
            else:
                del target["paths"]["/v1/services/inference/{service_role}/speak"]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"]["model_role"]
            with self.subTest(missing=missing), self.assertRaises(RuntimeError):
                self.verify(manifest, target)

    def test_unknown_build_identity_stays_closed_despite_native_schema(self):
        manifest = {"service_requirements": [{"role": "voice", "service": "inference", "operations": ["speak"]}]}
        for version in ("0.0.0+dev", "2.2.0-rc.8", "3.0.0", "unknown"):
            with self.subTest(version=version), self.assertRaises(RuntimeError):
                self.verify(manifest, inference_target(version))

    def test_snapshot_example_cannot_authorize_an_unknown_model_slot(self):
        manifest = load_json(EXAMPLES / "team-notes-manifest.json")
        manifest["model_requirements"] = [{"role": "voice", "slot": "invented"}]
        self.assertTrue(validate_manifest(manifest))

    def test_model_gate_rejects_wrong_types_and_malformed_enums(self):
        manifest = {"model_requirements": [{"role": "voice", "slot": "tts", "capabilities": ["tts"], "input_modalities": ["text"]}]}
        for malformed in ("requirements_type", "slot_type", "slot_enum", "capability_type", "capability_item_type", "capability_enum", "modality_type"):
            target = inference_target()
            schemas = target["components"]["schemas"]
            fields = schemas["ApplicationModelRequirement"]["properties"]
            if malformed == "requirements_type":
                schemas["ApplicationManifest"]["properties"]["model_requirements"]["anyOf"][0]["type"] = "object"
            elif malformed == "slot_type":
                fields["slot"]["type"] = "object"
            elif malformed == "slot_enum":
                fields["slot"]["enum"] = "tts"
            elif malformed == "capability_type":
                fields["capabilities"]["type"] = "object"
            elif malformed == "capability_item_type":
                fields["capabilities"]["items"]["type"] = "integer"
            elif malformed == "capability_enum":
                fields["capabilities"]["items"]["enum"] = ["tts", None]
            else:
                fields["input_modalities"]["type"] = "object"
            with self.subTest(malformed=malformed), self.assertRaises(RuntimeError):
                self.verify(manifest, target)

    def test_implicit_model_defaults_also_require_advertised_contract(self):
        manifest = {"model_requirements": [{"role": "voice", "slot": "tts"}]}
        self.verify(manifest, inference_target())
        for field in ("capabilities", "input_modalities"):
            for malformed in ("missing", "unsupported"):
                target = inference_target()
                fields = target["components"]["schemas"]["ApplicationModelRequirement"]["properties"]
                if malformed == "missing":
                    del fields[field]
                else:
                    fields[field]["items"]["enum"] = ["embedding"] if field == "capabilities" else ["audio"]
                with self.subTest(field=field, malformed=malformed), self.assertRaises(RuntimeError):
                    self.verify(manifest, target)

    def test_malformed_speech_route_has_sanitized_contract_failure(self):
        manifest = {"service_requirements": [{"role": "voice", "service": "inference", "operations": ["speak"]}]}
        for field in ("route", "post", "requestBody", "content", "application/json"):
            target = inference_target()
            route = target["paths"]["/v1/services/inference/{service_role}/speak"]
            if field == "route":
                target["paths"]["/v1/services/inference/{service_role}/speak"] = None
            elif field == "post":
                route["post"] = None
            elif field == "requestBody":
                route["post"]["requestBody"] = None
            elif field == "content":
                route["post"]["requestBody"]["content"] = None
            else:
                route["post"]["requestBody"]["content"]["application/json"] = None
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                self.verify(manifest, target)


if __name__ == "__main__":
    unittest.main()
