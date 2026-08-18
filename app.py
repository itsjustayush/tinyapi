import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template

load_dotenv()


def template_context():
    return {
        "supabase_url": os.environ.get("SUPABASE_URL"),
        "supabase_key": os.environ.get("SUPABASE_ANON_KEY")
        or os.environ.get("SUPABASE_KEY"),
    }


def create_app() -> Flask:
    app = Flask(__name__)

    from meteorbase.admin import bp as admin_bp
    from meteorbase.proxy import bp as gateway_bp
    from meteorbase.registry import bp as registry_bp

    app.register_blueprint(registry_bp)
    app.register_blueprint(gateway_bp)
    app.register_blueprint(admin_bp)

    # --- FRONTEND APP ROUTES ---

    @app.route("/")
    def home():
        return render_template("index.html")

    @app.route("/auth")
    def auth():
        return render_template("auth.html", **template_context())

    @app.route("/auth/callback")
    def auth_callback():
        return render_template("auth.html", **template_context())

    @app.route("/dashboard")
    def dashboard():
        return render_template("dashboard.html", **template_context())

    # --- SYSTEM HEALTH ---

    @app.route("/healthz")
    def healthz():
        """Liveness check for Render: the Flask process is accepting requests."""
        return jsonify({"service": "meteorbase", "status": "ok"}), 200

    @app.route("/readyz")
    def readyz():
        """Readiness check: required secrets exist and Supabase is reachable."""
        required = ("SUPABASE_URL", "SUPABASE_JWT_SECRET", "INTERNAL_SECRET")
        missing = [name for name in required if not os.environ.get(name)]
        if not (os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")):
            missing.append("SUPABASE_SERVICE_KEY or SUPABASE_KEY")
        if missing:
            return jsonify({"status": "not_ready", "missing": missing}), 503

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

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
