import os
from functools import wraps
from flask import Flask, request, render_template, jsonify, redirect, url_for, g
from supabase import create_client, Client
import jwt
from dotenv import load_dotenv

# Load environment variables for local testing
load_dotenv()

app = Flask(__name__)

# Initialize Supabase
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

# JWT Secret for server-side token validation
JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET")

def get_template_context():
    return {
        'supabase_url': supabase_url,
        'supabase_key': supabase_key
    }

@app.route('/auth/callback')
def auth_callback():
    # Renders the auth page so the Supabase JS client can parse the 
    # #access_token fragment in the URL and trigger the redirect to /dashboard
    return render_template('auth.html', **get_template_context())




# --- DECORATORS (The Security Layer) ---

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            return jsonify({"error": "Missing API Key header: X-API-Key"}), 401
        
        # Check if the API key exists in your Supabase 'api_keys' table
        response = supabase.table('api_keys').select('app_id').eq('api_key', api_key).execute()
        if not response.data:
            return jsonify({"error": "Invalid API Key"}), 403
        
        # Inject the App ID into Flask's global context
        g.app_id = response.data[0]['app_id']
        return f(*args, **kwargs)
    return decorated

def require_jwt(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        
        token = auth_header.split(" ")[1]
        try:
            # Decode and verify the JWT offline using your Supabase secret
            payload = jwt.decode(
                token, 
                JWT_SECRET, 
                algorithms=["HS256"], 
                audience="authenticated"
            )
            g.user_id = payload['sub']
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "User session has expired. Please log in again."}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid authentication token."}), 401
            
        return f(*args, **kwargs)
    return decorated

# --- FRONTEND APP ROUTES ---

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/auth')
def auth():
    return render_template('auth.html', **get_template_context())

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html', **get_template_context())

# --- SECURE API ENDPOINTS ---

@app.route('/ping')
def ping():
    try:
        # Keep-alive query for UptimeRobot
        supabase.table('profiles').select('id').limit(1).execute()
        return "OK - Render and Supabase are both awake!", 200
    except Exception as e:
        return f"Database error: {str(e)}", 500

@app.route('/api/v1/notes', methods=['GET'])
@require_api_key
@require_jwt
def get_notes():
    # Fetch notes filtered by both App ID and User ID
    response = supabase.table('notes') \
        .select('*') \
        .eq('app_id', g.app_id) \
        .eq('user_id', g.user_id) \
        .execute()
    return jsonify({"notes": response.data}), 200

@app.route('/api/v1/notes', methods=['POST'])
@require_api_key
@require_jwt
def create_note():
    content = request.json.get('content')
    if not content:
        return jsonify({"error": "Note content is required"}), 400
        
    data = {
        "app_id": g.app_id,
        "user_id": g.user_id,
        "content": content
    }
    response = supabase.table('notes').insert(data).execute()
    return jsonify({"status": "success", "note": response.data[0]}), 201

if __name__ == '__main__':
    app.run(debug=True)