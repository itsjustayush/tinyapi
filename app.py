from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template

load_dotenv()


BASE_DIR = Path(__file__).resolve().parent


def template_context() -> dict[str, str]:
    return {
        "supabase_url": os.environ.get("SUPABASE_URL", ""),
        "supabase_key": os.environ.get("SUPABASE_ANON_KEY")
        or os.environ.get("SUPABASE_KEY", ""),
        "base_url": os.environ.get("PUBLIC_BASE_URL", "https://tinyapi-urjr.onrender.com"),
    }


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.config.update(
        JSON_SORT_KEYS=False,
        MAX_CONTENT_LENGTH=int(os.environ.get("MAX_REQUEST_BYTES", str(2 * 1024 * 1024))),
    )

    from meteorbase.admin import bp as admin_bp
    from meteorbase.client import bp as client_bp
    from meteorbase.proxy import bp as gateway_bp
    from meteorbase.registry import bp as registry_bp

    app.register_blueprint(registry_bp)
    app.register_blueprint(client_bp)
    app.register_blueprint(gateway_bp)
    app.register_blueprint(admin_bp)

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response

    @app.route("/")
    def home():
        return render_template("index.html", **template_context())

    @app.route("/auth")
    @app.route("/auth/callback")
    def auth():
        return render_template("auth.html", **template_context())

    @app.route("/dashboard")
    def dashboard():
        return render_template("dashboard.html", **template_context())

    @app.route("/docs")
    def docs():
        return render_template("docs.html", **template_context())

    @app.route("/healthz")
    def healthz():
        return jsonify({"service": "meteorbase", "status": "ok"}), 200

    @app.route("/readyz")
    def readyz():
        required = ("SUPABASE_URL", "SUPABASE_JWT_SECRET", "INTERNAL_SECRET")
        missing = [name for name in required if not os.environ.get(name)]
        if not (os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")):
            missing.append("SUPABASE_SERVICE_KEY or SUPABASE_KEY")
        if missing:
            return jsonify({"service": "meteorbase", "status": "not_ready", "missing": missing}), 503

        try:
            from meteorbase.db import verify_gateway_schema

            verify_gateway_schema()
            return jsonify({"service": "meteorbase", "status": "ready"}), 200
        except Exception:
            app.logger.exception("MeteorBase readiness check failed")
            return jsonify({"status": "not_ready", "reason": "schema_or_database_unavailable"}), 503

    @app.route("/ping")
    def ping():
        return readyz()

    @app.errorhandler(413)
    def request_too_large(_error):
        return jsonify({"error": "Request body exceeds the configured size limit."}), 413

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=os.environ.get("FLASK_DEBUG") == "1")
