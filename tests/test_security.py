import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
from flask import Flask

from examples.meteorbase_receiver import require_meteorbase
from meteorbase.proxy import _normalize_path, _safe_service_url
from meteorbase.security import API_KEY_PREFIX, api_key_prefix, canonical_api_key, decode_user_jwt, hash_api_key


class SecurityHelpersTests(unittest.TestCase):
    def test_key_hash_is_stable_and_does_not_include_prefix(self):
        raw = f"{API_KEY_PREFIX}abc123"
        self.assertEqual(canonical_api_key(raw), "abc123")
        self.assertEqual(api_key_prefix(raw), f"{API_KEY_PREFIX}abc123")
        self.assertNotIn(raw, hash_api_key(raw))
        self.assertEqual(hash_api_key(raw), hash_api_key(raw))

    def test_private_targets_are_rejected(self):
        self.assertFalse(_safe_service_url("http://127.0.0.1:9000"))
        self.assertFalse(_safe_service_url("http://10.0.0.2"))
        self.assertFalse(_safe_service_url("file:///etc/passwd"))
        self.assertTrue(_safe_service_url("https://example.com"))

    def test_paths_are_normalized_for_endpoint_comparison(self):
        self.assertEqual(_normalize_path("sessions/"), "/sessions")
        self.assertEqual(_normalize_path("/"), "/")

    def test_supabase_jwt_is_verified(self):
        now = datetime.now(timezone.utc)
        token = jwt.encode({"sub": "user-1", "aud": "authenticated", "iat": now, "exp": now + timedelta(minutes=5)}, "test-secret", algorithm="HS256")
        with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": "test-secret", "SUPABASE_JWT_AUDIENCE": "authenticated"}, clear=False):
            with patch("meteorbase.security.JWT_SECRET", "test-secret"):
                claims = decode_user_jwt(token)
        self.assertEqual(claims["sub"], "user-1")


class ReceiverGuardTests(unittest.TestCase):
    def test_receiver_requires_both_trust_headers(self):
        app = Flask(__name__)

        @app.get("/private")
        @require_meteorbase
        def private():
            return {"ok": True}

        with patch("examples.meteorbase_receiver.INTERNAL_SECRET", "internal"), patch("examples.meteorbase_receiver.SERVICE_SECRET", "service"):
            client = app.test_client()
            self.assertEqual(client.get("/private").status_code, 403)
            self.assertEqual(client.get("/private", headers={"X-Internal-Secret": "internal", "X-Service-Secret": "service", "X-User-ID": "user-1"}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
