# Provenance Guard — Planning Doc

A backend system that any creative sharing platform could plug into to classify submitted content, score confidence in that classification, surface a transparency label to users, and handle appeals from creators who believe they've been misclassified.

---

## Architecture

User submits a query to POST/submit ---> FLASK checks rate limit --> query is passed to Signal 1 ( Stylometric analysis) measures statistical properties that differ human and AI writing which return its own score of the query --> query is also passed to Signal 2(Groq LLM call) assess whether text reads as human or AI-generated, captures semantic ans stylistic coherence holistically which returns a score/verdict ==> both scores are combined into one confidence score --> confidence score is mapped to one of the three transparency labels --> the detection (signals, scores, label) is written to the audit log --> response is return to the user with the label + confidence + result

### Signal Blind spots

 Groq's holistic judgment can mistake a human's sophisticated or unusual vocabulary for an AI "trying too hard," since large language models are trained partly on other AI outputs that skew toward polished word choice — it can't distinguish a well-read human from a model. Stylometric heuristics can mistake a human writer with a very consistent, controlled style — technical writers, formal essayists, some poets — for AI-generated text, since the heuristic only measures variance (sentence length, vocabulary diversity, punctuation density) and can't tell *why* that variance is low. A disciplined human writer and an AI model can both produce low-variance text for completely different reasons.

### False Positive

In a false-positive scenario the where a human writier submits something, that my systems leans toward "AI-generated" incorrectly I'd expect a borderline confidence score (something like 0.55-0.65), not a high one — because a genuinely uncertain/ambiguous case is precisely what produces mixed signals in the first place. If my two signals disagree (say, Groq says "AI" but stylometry says "human"), that disagreement itself should pull the combined confidence toward the middle. This is where the label is "uncertain", this should communicate a mixed signal to the user when the result is return, so more caution is taken. This is appealed by submitting the reasoning via POST /appeal, it gets logged alongside the original decision, and the content's status flips to "under review" — per the required feature.


### API surface Sketch:

```text
POST /submit    → accepts text, returns {result, confidence, label}
POST /appeal    → accepts content_id + reasoning, returns updated status
GET  /log       → returns audit log entries
```

### Submission Flow

```text
                    ┌─────────────────┐
   POST /submit --->│  Rate Limiter    │
   (raw text)       │  (Flask-Limiter) │
                    └────────┬─────────┘
                             │ text
                             ▼
                    ┌──────────────────────┐
                    │ Signal 1: Stylometry  │
                    │ (sentence variance,   │
                    │  type-token ratio,    │
                    │  punctuation density) │
                    └────────┬─────────────┘
                             │ stylometric_score
                             ▼
                    ┌──────────────────────┐
                    │ Signal 2: Groq LLM    │
                    │ (semantic/stylistic   │
                    │  coherence judgment)  │
                    └────────┬─────────────┘
                             │ llm_score / verdict
                             ▼
                    ┌──────────────────────┐
                    │ Combine Scores        │
                    │ -> confidence_score   │
                    └────────┬─────────────┘
                             │ confidence_score
                             ▼
                    ┌──────────────────────┐
                    │ Map to Transparency   │
                    │ Label (AI / Human /   │
                    │ Uncertain)            │
                    └────────┬─────────────┘
                             │ label + confidence + result
                             ▼
                    ┌──────────────────────┐
                    │ Write to Audit Log    │
                    │ (signals, score,      │
                    │  label)               │
                    └────────┬─────────────┘
                             │
                             ▼
                    ┌──────────────────────┐
                    │ Response to User      │
                    │ {result, confidence,  │
                    │  label}               │
                    └──────────────────────┘
```

### Appeal Flow

```text
                    ┌──────────────────────┐
   POST /appeal --->│ Capture Creator's     │
   (content_id,     │ Reasoning             │
    reasoning)      └────────┬─────────────┘
                             │ content_id, reasoning, original_decision
                             ▼
                    ┌──────────────────────┐
                    │ Write to Audit Log    │
                    │ (appeal logged        │
                    │  alongside original)  │
                    └────────┬─────────────┘
                             │
                             ▼
                    ┌──────────────────────┐
                    │ Update Content Status │
                    │ -> "under review"     │
                    └────────┬─────────────┘
                             │
                             ▼
                    ┌──────────────────────┐
                    │ Response to User      │
                    │ {status: "under       │
                    │  review"}             │
                    └──────────────────────┘
```

## Thresholds

Likely AI (score 0.65–1.00):

"This content shows strong signals of AI generation."

Uncertain (score 0.35–0.65):

"We could not confidently determine whether this content is AI-generated or human-written. Mixed signals were detected."

Likely human (score 0.00–0.35):

"This content shows strong signals of human authorship."

## AI Tool Plan

### M3 — Submission endpoint + first signal
- Spec sections provided: Detection Signals (stylometric portion), Architecture diagram
- What I'll ask for: A Flask app skeleton with a POST /submit endpoint, plus a standalone stylometric_score(text) function implementing sentence length variance, type-token ratio, and punctuation density, normalized to 0–1
- Verification: Run stylometric_score() directly against 3-4 sample texts (one obviously uniform/robotic, one obviously varied/human) before wiring it into the endpoint. Confirm scores trend in the expected direction.

### M4 — Second signal + confidence scoring
- Spec sections provided: Detection Signals (Groq portion + combination formula), Uncertainty Representation (thresholds), Architecture diagram
- What I'll ask for: A groq_score(text) function that prompts Groq for a verdict + confidence and converts it to the 0–1 "AI-likelihood" scale, plus a combine_scores() function implementing the 0.6/0.4 weighting
- Verification: Test combine_scores() with hand-picked score pairs (e.g., both signals agree it's AI, both agree it's human, signals disagree) and confirm the combined score lands in the expected threshold band each time

### M5 — Production layer (labels + appeals)
- Spec sections provided: Transparency Label Design (three label variants), Appeals Workflow, Architecture diagram
- What I'll ask for: A get_label(confidence_score) function mapping score to the correct label text, plus a POST /appeal endpoint that logs the appeal and updates content status to "under review"
- Verification: Call get_label() with a score from each of the three bands and confirm the correct exact label text is returned; submit a test appeal and confirm the audit log gets a new entry and the content status changes correctly

## Edge Cases

### Edge case 1: Non-native or ESL writing patterns

A non-native English speaker's writing often uses simpler sentence structures, more repetition of common phrases, and less lexical variety than a fluent native speaker's — the same surface properties our stylometric signal associates with AI-generated text. This could produce a false "likely AI" or "uncertain" result for a human writer whose only "issue" is writing in a non-native language.

### Edge case 2: Heavily human-edited AI output

If a creator generates a first draft with an AI tool and then substantially rewrites it — changing word choice, restructuring sentences, adding personal anecdotes — the result may read as natural and varied to both signals. Groq's holistic judgment may see coherent, human-sounding prose, and stylometry may see natural variance, so the system could confidently label AI-origin content as "likely human," missing the AI origin entirely.