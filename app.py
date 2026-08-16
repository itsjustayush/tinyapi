from flask import Flask, request, render_template, jsonify

app = Flask(__name__)

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
@app.route('/ping')
def ping():
    return "OK", 200

if __name__ == '__main__':
    app.run(debug=True)