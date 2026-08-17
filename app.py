import os

from dotenv import load_dotenv
from flask import Flask, render_template

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

    # --- SYSTEM HEALTH (keeps Render + Supabase awake) ---

    @app.route("/ping")
    def ping():
        try:
            from meteorbase.db import get_supabase

            get_supabase().table("profiles").select("id").limit(1).execute()
            return "OK - MeteorBase and Supabase are both awake!", 200
        except Exception as e:
            return f"Database error: {str(e)}", 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)