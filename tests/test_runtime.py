import importlib
import os
import unittest
from unittest.mock import MagicMock, patch

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

    @patch("meteorbase.db.verify_gateway_schema")
    def test_readiness_fails_closed_when_the_gateway_schema_is_incomplete(self, verify_schema):
        required = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_KEY": "service-role-key",
            "SUPABASE_JWT_SECRET": "jwt-secret",
            "INTERNAL_SECRET": "internal-secret",
        }
        verify_schema.side_effect = RuntimeError("missing services.display_name")
        with patch.dict(os.environ, required, clear=True):
            response = self.client.get("/readyz")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {"status": "not_ready", "reason": "schema_or_database_unavailable"})

    @patch("meteorbase.db.verify_gateway_schema")
    def test_readiness_accepts_the_deployed_supabase_key_alias(self, verify_schema):
        legacy_render_environment = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_KEY": "service-role-key",
            "SUPABASE_JWT_SECRET": "jwt-secret",
            "INTERNAL_SECRET": "internal-secret",
        }
        with patch.dict(os.environ, legacy_render_environment, clear=True):
            response = self.client.get("/readyz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"service": "meteorbase", "status": "ready"})

    @patch("meteorbase.registry.get_supabase")
    def test_public_registry_reports_a_controlled_error_when_supabase_is_unavailable(self, mocked_client):
        mocked_client.side_effect = RuntimeError("connection unavailable")
        response = self.client.get("/api/v1/apps")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {"error": "Registry database is unavailable"})

    @patch("meteorbase.registry.get_supabase")
    def test_public_registry_reports_a_controlled_error_when_the_schema_is_incomplete(self, mocked_client):
        db = MagicMock()
        db.table.return_value.select.return_value.order.return_value.execute.side_effect = RuntimeError("column services.display_name does not exist")
        mocked_client.return_value = db
        response = self.client.get("/api/v1/apps")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {"error": "Registry schema or database is unavailable"})


class ApiKeyNormalizationTests(unittest.TestCase):
    def test_accepts_the_documented_public_key_prefix(self):
        self.assertEqual(
            security.canonical_api_key("mb_live_68e8d085-235d-44ef-9cdf-29a831893325"),
            "68e8d085-235d-44ef-9cdf-29a831893325",
        )

    def test_preserves_legacy_unprefixed_keys(self):
        self.assertEqual(security.canonical_api_key("legacy-key"), "legacy-key")
