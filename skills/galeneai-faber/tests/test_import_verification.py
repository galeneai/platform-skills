"""Import readiness and intended-image checks without a running platform."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from verify_import import verify_import


class ImportVerificationTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "references/contracts/examples/multi-component-archive-import-manifest.json").read_text())
        self.expected = {"web": "acme/web:1.2.0", "api": "acme/api:1.2.0"}
        self.status = {"status": "ready", "result_version_id": "fictional-version", "component_names": ["web", "api"],
            "component_mappings": {"web": "docker-9", "api": "docker-0"},
            "component_digests": {"web": "sha256:" + "a" * 64, "api": "sha256:" + "b" * 64},
            "candidate_images": [{"id": "docker-0", "reference": self.expected["api"], "platforms": [{"os": "linux", "architecture": "amd64"}]},
                {"id": "docker-9", "reference": self.expected["web"], "platforms": [{"os": "linux", "architecture": "amd64"}]}],
            "upload_url": "https://example.invalid/private-staging-url"}

    def test_verifies_returned_ids_without_order_assumptions_or_echoing_private_metadata(self):
        result = verify_import(self.manifest, self.status, self.expected, "linux/amd64")
        self.assertEqual(result["components"]["web"]["candidate_id"], "docker-9")
        self.assertFalse(result["deployment_verified"])
        self.assertNotIn("private-staging-url", json.dumps(result))

    def test_queued_copy_or_partial_digests_cannot_be_installed(self):
        queued = copy.deepcopy(self.status); queued["status"] = "queued"
        with self.assertRaises(ValueError): verify_import(self.manifest, queued, self.expected)
        partial = copy.deepcopy(self.status); del partial["component_digests"]["web"]
        with self.assertRaises(ValueError): verify_import(self.manifest, partial, self.expected)

    def test_swapped_images_and_wrong_platform_are_rejected(self):
        swapped = copy.deepcopy(self.status); swapped["component_mappings"] = {"web": "docker-0", "api": "docker-9"}
        with self.assertRaises(ValueError): verify_import(self.manifest, swapped, self.expected)
        with self.assertRaises(ValueError): verify_import(self.manifest, self.status, self.expected, "linux/arm64")

    def test_reused_candidate_is_supported_when_explicitly_intended(self):
        reused = copy.deepcopy(self.status); reused["component_mappings"]["web"] = "docker-0"
        result = verify_import(self.manifest, reused, {"web": self.expected["api"], "api": self.expected["api"]})
        self.assertEqual(result["components"]["web"]["candidate_id"], result["components"]["api"]["candidate_id"])


if __name__ == "__main__": unittest.main()
