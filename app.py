import os
from functools import wraps
from flask import Flask, request, render_template, jsonify, g
from supabase import create_client, Client
import jwt
from dotenv import load_dotenv
import requests

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Initialize Supabase
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

# JWT Secret for server-side token validation
JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET")
INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "super-secret-gateway-token")

def get_template_context():
    return {
        'supabase_url': supabase_url,
        'supabase_key': supabase_key
    }

# --- SECURITY DECORATORS ---

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            return jsonify({"error": "Missing API Key header: X-API-Key"}), 401
        
        # Validate API key from MeteorBase api_keys table
        response = supabase.table('api_keys').select('user_id').eq('api_key', api_key).execute()
        if not response.data:
            return jsonify({"error": "Invalid API Key"}), 403
        
        # Inject verified user_id into Flask global context
        g.user_id = response.data[0]['user_id']
        return f(*args, **kwargs)
    return decorated

# --- FRONTEND APP ROUTES ---

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/auth')
def auth():
    return render_template('auth.html', **get_template_context())

@app.route('/auth/callback')
def auth_callback():
    return render_template('auth.html', **get_template_context())

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html', **get_template_context())

# --- SYSTEM HEALTH ---

@app.route('/ping')
def ping():
    try:
        supabase.table('profiles').select('id').limit(1).execute()
        return "OK - Render and Supabase are both awake!", 200
    except Exception as e:
        return f"Database error: {str(e)}", 500

# --- THE UNIVERSAL API GATEWAY PROXY ---

@app.route('/api/v1/<app_name>/<path:endpoint>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
@require_api_key
def api_gateway(app_name, endpoint):
    try:
        # 1. Look up microservice URL dynamically from the Supabase 'services' table
        service_res = supabase.table('services').select('target_url', 'is_active').eq('name', app_name.lower()).execute()
        
        if not service_res.data or not service_res.data[0]['is_active']:
            return jsonify({"error": f"Service '{app_name}' is unregistered, invalid, or inactive."}), 404
            
        target_base_url = service_res.data[0]['target_url'].rstrip('/')
        target_url = f"{target_base_url}/{endpoint}"
        
        # 2. Build secure forward headers
        headers = {
            "Content-Type": request.headers.get("Content-Type", "application/json"),
            "X-Internal-Secret": INTERNAL_SECRET,
            "X-User-ID": g.user_id
        }
        
        params = request.args
        data = request.get_data()
        
        # 3. Proxy the request to the target microservice
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers=headers,
            params=params,
            data=data,
            timeout=15
        )
        
        # 4. Pipe response back to the client
        return (resp.content, resp.status_code, resp.headers.items())
        
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to communicate with service '{app_name}'.", "details": str(e)}), 502
    except Exception as e:
        return jsonify({"error": "Gateway routing exception.", "details": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)