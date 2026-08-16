import os
from flask import Flask, request, render_template, jsonify
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables from .env for local testing
load_dotenv()

app = Flask(__name__)

# Initialize the Supabase connection
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

# In-memory list to store notes (resets if the server restarts)
notes = []

@app.route('/')
def home():
    # Renders the HTML frontend
    return render_template('index.html')

@app.route('/api/notes', methods=['GET', 'POST'])
def handle_notes():
    if request.method == 'POST':
        # Add a new note
        note_content = request.json.get('note')
        if note_content:
            notes.append(note_content)
            return jsonify({"status": "success", "message": "Note added!"}), 201
        return jsonify({"status": "error", "message": "Note content is required."}), 400
    
    # GET request: Return all notes
    return jsonify({"notes": notes})

# Dedicated lightweight endpoint for UptimeRobot
# This queries the database to keep Supabase awake (prevents 7-day pause)
@app.route('/ping')
def ping():
    try:
        # 1. This simple query tells Supabase there is active API traffic
        # We limit it to 1 just so it doesn't waste bandwidth transferring data
        supabase.table('notes').select('*').limit(1).execute()
        
        # 2. Return success to UptimeRobot
        return "OK - Render and Supabase are both awake!", 200
    
    except Exception as e:
        # If Supabase is down or fails, UptimeRobot will alert you
        return f"Database error: {str(e)}", 500

if __name__ == '__main__':
    app.run(debug=True)