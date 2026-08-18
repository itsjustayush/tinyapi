import importlib
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("INTERNAL_SECRET", "test-internal-secret")

import app as meteorbase_app
from meteorbase import security
from meteorbase import registry


class RuntimeHealthTests(unittest.TestCase):
    def setUp(self):
        self.client = meteorbase_app.create_app().test_client()

    def test_liveness_does_not_depend_on_supabase(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"service": "meteorbase", "status": "ok"})

    def test_readiness_reports_missing_required_configuration_without_secret_details(self):
        with patch.dict(os.environ, {}, clear=True):
            response = self.client.get("/readyz")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["status"], "not_ready")
        self.assertIn("SUPABASE_URL", response.get_json()["missing"])

    @patch("meteorbase.registry.get_supabase")
    def test_public_registry_reports_a_controlled_error_when_supabase_is_unavailable(self, mocked_client):
        mocked_client.side_effect = RuntimeError("connection unavailable")
        response = self.client.get("/api/v1/apps")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {"error": "Registry database is unavailable"})


class ApiKeyNormalizationTests(unittest.TestCase):
    def test_accepts_the_documented_public_key_prefix(self):
        self.assertEqual(
            security.canonical_api_key("mb_live_68e8d085-235d-44ef-9cdf-29a831893325"),
            "68e8d085-235d-44ef-9cdf-29a831893325",
        )

    def test_preserves_legacy_unprefixed_keys(self):
        self.assertEqual(security.canonical_api_key("legacy-key"), "legacy-key")
