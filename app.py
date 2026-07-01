"""
app.py — Provenance Guard Flask application.

Current state (M3): POST /submit skeleton only.
Groq signal, score combination, labeling, rate limiting, and
/appeal + /log routes are added in later milestones.
"""

from flask import Flask, request, jsonify
from signals import stylometric_score

app = Flask(__name__)


@app.route('/submit', methods=['POST'])
def submit():
    data = request.get_json(silent=True)

    if not data or 'text' not in data:
        return jsonify({'error': 'Request body must include a "text" field.'}), 400

    text = data['text']

    if not text.strip():
        return jsonify({'error': '"text" must not be empty.'}), 400

    # --- Signal 1 (available now) ---
    stylo_score = stylometric_score(text)

    # --- Signal 2 placeholder (Groq — added in M4) ---
    groq_score = None  # noqa: F841

    # --- Score combination placeholder (added in M4) ---
    confidence = stylo_score   # temporary: use only signal 1 for now

    # --- Label placeholder (added in M5) ---
    label = 'pending'
    result = 'pending'

    return jsonify({
        'result': result,
        'confidence': confidence,
        'label': label,
    })


if __name__ == '__main__':
    app.run(debug=True)
