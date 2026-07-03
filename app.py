"""
app.py — Provenance Guard Flask application.

Routes:
  POST /submit  — run both signals, return classification + label text
  POST /appeal  — log a creator appeal and flip status to under_review
  GET  /log     — return recent audit log entries
"""

import uuid

from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from signals import (
    groq_score,
    stylometric_score,
    combine_scores,
    get_attribution_label,
    get_label_text,
)
from audit_log import log_entry, get_entry, update_appeal, get_recent_entries

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


@app.route('/submit', methods=['POST'])
@limiter.limit("10 per minute;100 per day")
def submit():
    data = request.get_json(silent=True)

    if not data or 'text' not in data:
        return jsonify({'error': 'Request body must include a "text" field.'}), 400

    text = data['text']

    if not text.strip():
        return jsonify({'error': '"text" must not be empty.'}), 400

    content_id = str(uuid.uuid4())
    creator_id = data.get('creator_id', 'anonymous')

    # --- Signal 1: Groq LLM judgment ---
    llm_score = groq_score(text)

    # --- Signal 2: Stylometric analysis ---
    stylo_score = stylometric_score(text)

    # --- Combine into final confidence ---
    confidence = combine_scores(llm_score, stylo_score)

    # --- Label category and human-readable label text ---
    attribution = get_attribution_label(confidence)
    label = get_label_text(confidence)

    log_entry(
        content_id=content_id,
        creator_id=creator_id,
        llm_score=llm_score,
        stylometric_score=stylo_score,
        confidence=confidence,
        attribution=confidence,
        status='classified',
    )

    return jsonify({
        'content_id': content_id,
        'attribution': attribution,
        'confidence': confidence,
        'label': label,
    })


@app.route('/appeal', methods=['POST'])
def appeal():
    data = request.get_json(silent=True)

    if not data or 'content_id' not in data or 'creator_reasoning' not in data:
        return jsonify({
            'error': 'Request body must include "content_id" and "creator_reasoning".'
        }), 400

    content_id = data['content_id']
    reasoning = data['creator_reasoning']

    if not reasoning.strip():
        return jsonify({'error': '"creator_reasoning" must not be empty.'}), 400

    entry = get_entry(content_id)
    if entry is None:
        return jsonify({'error': f'No submission found for content_id "{content_id}".'}), 404

    update_appeal(content_id, reasoning)

    return jsonify({
        'content_id': content_id,
        'status': 'under_review',
        'message': 'Appeal received',
    })


@app.route('/log', methods=['GET'])
def log():
    return jsonify({'entries': get_recent_entries()})


if __name__ == '__main__':
    app.run(debug=True)
