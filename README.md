# Provenance Guard

A backend system that creative sharing platforms can plug into to classify submitted content as AI-generated or human-written, score confidence in that classification, surface a transparency label to users, and handle appeals from creators who believe they've been misclassified.

---

## How It Works

Content submitted to `POST /submit` passes through two independent detection signals. Their scores are combined into a single confidence score, which is mapped to a transparency label. Every decision — signals, scores, and label — is written to an audit log. The raw confidence score is always returned in the API response for platform/developer use; it is intentionally not shown in the label copy shown to end users.

### Submission Flow

```
POST /submit
(raw text)
    │
    ▼
Rate Limiter (Flask-Limiter)
    │
    ├──────────────────────────────────────────────┐
    ▼                                              ▼
Signal 1: Groq LLM                       Signal 2: Stylometry
(semantic / stylistic                    (sentence length variance,
 coherence judgment)                      type-token ratio,
                                          punctuation density)
    │ llm_score                               │ stylometric_score
    └──────────────┬──────────────────────────┘
                   ▼
           Combine Scores
           → confidence_score (0.6 × Groq + 0.4 × stylometry)
                   │
                   ▼
           Map to Transparency Label
           (Likely AI / Uncertain / Likely Human)
                   │
                   ▼
           Write to Audit Log
           (both signal scores, combined confidence, label, status)
                   │
                   ▼
           Response: { content_id, attribution, confidence, label }
```

### Appeal Flow

```
POST /appeal
(content_id, creator_reasoning)
    │
    ▼
Look up original submission by content_id (404 if not found)
    │
    ▼
Store creator_reasoning, flip status → "under_review"
    │
    ▼
Response: { content_id, status: "under_review", message }
```

---

## API

| Method | Endpoint  | Body                                    | Returns                                      |
|--------|-----------|-----------------------------------------|----------------------------------------------|
| POST   | `/submit` | `{ text, creator_id? }`                | `{ content_id, attribution, confidence, label }` |
| POST   | `/appeal` | `{ content_id, creator_reasoning }`    | `{ content_id, status, message }`            |
| GET    | `/log`    | —                                       | `{ entries: [...] }`                         |

---

## Detection Signals

### Why these two signals?

AI detection is fundamentally a signal-fusion problem — no single test is reliable enough on its own. I chose one statistical signal and one LLM-based signal specifically because they fail in different ways. Stylometry is deterministic and explainable but blind to meaning; it only sees surface variance. The Groq signal understands semantics and register but inherits LLM biases. When the two agree, confidence goes up. When they disagree, the combined score lands in the middle — which is the honest answer for a genuinely ambiguous case, and the one that routes the submission to the "uncertain" label rather than forcing a confident wrong call.

### Signal 1 — Groq LLM Judgment

A Groq LLM call (`llama-3.3-70b-versatile`) receives the submitted text and is prompted to return a structured JSON verdict: `{"verdict": "ai"|"human", "confidence": float}`. The raw confidence is converted to a 0–1 AI-likelihood score: if the verdict is `"ai"`, the confidence is used directly; if `"human"`, it is flipped (`1.0 - confidence`).

**Why Groq as Signal 1?** An LLM can assess whether prose *feels* human — it picks up on hedging language, idiosyncratic phrasing, register inconsistencies, and whether a piece has the kind of personal specificity that AI models tend to flatten out. These are things no statistical formula can capture. The limitation is that Groq's training data includes a lot of AI-generated text, so it has internalized what "AI-sounding" means — and that pattern can match any formal, polished human writer, not just models. This is a real, documented failure mode, not a theoretical one (see Known Limitations).

**What I'd change for real deployment:** I would add a system prompt with few-shot examples, calibrated specifically on the platform's content type. A creative writing platform and a technical documentation platform have completely different baseline registers. A generic prompt — which is what this system uses — is a reasonable starting point, but it would need to be domain-tuned to reduce false positives in specialist writing.

### Signal 2 — Stylometric Analysis

Measures three surface-level statistical properties and averages them into a single score in [0, 1], where 1 = AI-like uniformity:

- **Sentence length variance** — AI output tends toward uniform sentence lengths; human writing varies more. Computed as `1 / (1 + variance/20)` — a variance of 20 words² maps to a neutral 0.5.
- **Type-token ratio (TTR)** — `unique_words / total_words`. Lower lexical diversity is associated with AI output. Score = `1 - TTR`.
- **Punctuation density variance** — AI text tends toward consistent punctuation patterns across sentences. Computed the same way as sentence length variance, normalized to a smaller scale (0.005) appropriate to per-character densities.

**Why stylometry?** It's deterministic, requires no API call, and produces an explainable score with no hallucination risk. It also fails in a completely different direction from the LLM signal: it has no concept of *meaning*, only shape. A technical writer with a controlled, precise style and an AI model can produce identically low-variance text for completely different reasons — stylometry can't distinguish them. That's fine: that's exactly what the "uncertain" band exists for.

**What I'd change for real deployment:** The normalization scales (variance/20, variance/0.005) were tuned manually by testing against a small set of sample texts. In a real system I'd calibrate these against a labeled corpus to set the midpoints empirically rather than by feel. I'd also look at adding a readability signal (Flesch-Kincaid or similar), since AI text tends toward a specific readability band that neither sentence length nor TTR fully captures.

### Score Combination

```
confidence = (0.6 × groq_score) + (0.4 × stylometric_score)
```

Groq carries 60% of the weight because its holistic semantic judgment captures properties that stylometry structurally cannot — meaning, register, tone, and specificity. Stylometry gets 40% as a grounding signal: it can't be fooled by clever prompting, it's fully explainable, and it pulls the combined score toward the middle when the signals disagree. The asymmetry reflects the difference in what each signal can actually see, not an assumption that one is universally more accurate.

### Example Submissions

**High-confidence case — likely AI-generated**

Input: *"Mitochondria are organelles found in eukaryotic cells that generate the majority of the cell's supply of ATP through the process of oxidative phosphorylation. They contain their own DNA and ribosomes, suggesting an endosymbiotic origin."*

```json
{
  "llm_score": 0.846,
  "stylometric_score": 0.4938,
  "confidence": 0.70512,
  "attribution": "likely_ai",
  "label": "This content shows strong signals of AI generation."
}
```

Both signals lean AI. The Groq score is high (0.846) — the prose reads as textbook-formal with no personal register. Stylometry is moderate (0.494) — the sentences are fairly uniform in structure. Combined confidence: 0.705, landing clearly above the 0.65 threshold.

---

**Lower-confidence case — likely human-written**

Input: *"The sun dipped below the horizon, painting the sky in amber and rose."*

```json
{
  "llm_score": 0.154,
  "stylometric_score": 0.4282,
  "confidence": 0.26368,
  "attribution": "likely_human",
  "label": "This content shows strong signals of human authorship."
}
```

Groq reads this as human-written (score 0.154 — low AI-likelihood). Stylometry is moderate. Combined: 0.264, well below 0.35. The scoring produces meaningful separation between these two cases: 0.70 vs 0.26 is not noise.

---

## Transparency Labels

Three label variants are defined, keyed to confidence score bands. The exact text shown to users:

**Likely AI-generated** (confidence > 0.65):
> "This content shows strong signals of AI generation."

**Uncertain** (0.35 ≤ confidence ≤ 0.65):
> "We could not confidently determine whether this content is AI-generated or human-written. Mixed signals were detected."

**Likely human-written** (confidence < 0.35):
> "This content shows strong signals of human authorship."

Boundary values (exactly 0.35 or exactly 0.65) fall into "uncertain" — a deliberate choice to avoid confident calls at the edge of a threshold, where genuine ambiguity is highest.

The raw confidence score is always returned in the API response (`confidence` field) for the platform to use programmatically. The label text above is what gets surfaced to end users — the percentage or raw float is not shown in the user-facing copy, since a score like 0.67 conveys false precision to a non-technical reader.

---

## Audit Log

Every call to `POST /submit` writes a structured JSON entry to a SQLite database (`audit_log.db`). The log captures all required fields: timestamp, content ID, both individual signal scores, combined confidence, attribution result, and appeal status.

Entries are retrievable via `GET /log`.

### Sample Entries

**Entry 1 — Likely AI-generated**

```json
{
  "content_id": "21e39856-e5ae-4c9d-a0d5-8ef866af4b14",
  "creator_id": "writer-1",
  "timestamp": "2026-07-02T23:34:14.122850+00:00",
  "llm_score": 0.846,
  "stylometric_score": 0.4938,
  "confidence": 0.70512,
  "attribution": 0.70512,
  "status": "classified",
  "appeal_reasoning": null
}
```
Label shown to user: *"This content shows strong signals of AI generation."*

---

**Entry 2 — Likely human-written**

```json
{
  "content_id": "ff5fea65-f3fb-446c-b61e-a58358d47c04",
  "creator_id": "writer-2",
  "timestamp": "2026-07-02T23:34:35.087756+00:00",
  "llm_score": 0.154,
  "stylometric_score": 0.4282,
  "confidence": 0.26368,
  "attribution": 0.26368,
  "status": "classified",
  "appeal_reasoning": null
}
```
Label shown to user: *"This content shows strong signals of human authorship."*

---

**Entry 3 — False positive, appealed**

```json
{
  "content_id": "cf844d8b-79b5-44e3-a1c6-9a5c76a2294c",
  "creator_id": "writer-3",
  "timestamp": "2026-07-02T23:34:45.472691+00:00",
  "llm_score": 0.817,
  "stylometric_score": 0.5,
  "confidence": 0.6902,
  "attribution": 0.6902,
  "status": "under_review",
  "appeal_reasoning": "I wrote this myself. I write in a formal academic register for my field, which may read as artificial."
}
```
Label shown to user: *"This content shows strong signals of AI generation."*
This entry was appealed — see Known Limitations for full discussion.

---

## Appeals

When a creator believes their content was misclassified, they submit `POST /appeal` with their `content_id` and written reasoning. The appeal is logged alongside the original detection decision and the content status flips to `"under_review"`. Appeals do not automatically override the original label; they surface the case for human review.

A false positive typically produces a borderline confidence score rather than a high one — because a genuinely ambiguous case produces mixed signals, and mixed signals pull the combined score toward the middle. The "uncertain" label is designed to communicate this upfront. High-confidence false positives (like the formal academic case in Known Limitations) are the harder, rarer cases — and the appeals workflow is the correct mitigation for them.

---

## Rate Limiting

`POST /submit` is limited to **10 requests per minute and 100 per day** per client IP, enforced via Flask-Limiter. `/appeal` and `/log` are unrestricted.

**Reasoning:** A real creator submitting original work would rarely submit more than a handful of pieces in a single sitting. 10 per minute comfortably covers even a writer batch-checking several short pieces at once. The 100/day ceiling accommodates a creator who returns to the platform multiple times without limiting legitimate use. Both limits make automated flooding (a script submitting hundreds of requests to probe or overload the detection pipeline) immediately visible and throttled.

**Verified behavior** — 12 rapid requests, limit 10/minute:

```
200 200 200 200 200 200 200 200 200 200 429 429
```

The first 10 succeed; requests 11 and 12 are rejected with `429 Too Many Requests`.

---

## Known Limitations

### Formal register false positive

**The failure:** Formal academic or technical writing — controlled vocabulary, measured tone, hedged claims, domain-specific jargon — shares surface features with AI-generated text. The Groq signal in particular is prone to this: it was trained on a lot of AI output, which skews toward polished, authoritative register. It can't reliably distinguish "well-read human writing carefully" from "language model generating a plausible paragraph."

**Concrete example:**

Input: *"The relationship between monetary policy and asset price inflation has been extensively studied in the literature. Central banks face a fundamental tension between their mandate for price stability and the unintended consequences of prolonged low interest rates on equity and real estate valuations."*

Result: `groq_score=0.817`, `stylometric_score=0.512`, `combined=0.695`, label: `"likely_ai"` — a high-confidence wrong call on genuinely human-authored text.

**Why this happens in terms of the signals:** The Groq signal fires because the prose is hedge-heavy, uses domain vocabulary, and reads as authoritative — all features the model associates with AI. The stylometric signal is neutral (0.512) because the sentences are moderately varied. The Groq signal's 60% weight pulls the combined score above 0.65 even though stylometry is essentially saying "I'm not sure."

**What I chose not to do:** I did not widen the "uncertain" band to absorb this case. Doing so after seeing this single result would be overfitting a threshold to one test case. If I were to recalibrate, I'd do it against a representative labeled corpus — not a single anecdote.

**The correct mitigation:** The appeals workflow. A human writer misclassified this way can contest the result, which gets logged and surfaced for human review.

---

## Spec Reflection

**One way the spec guided implementation directly:** The spec's insistence on a two-signal architecture — rather than just one — was the most consequential constraint. My initial instinct was to lean on Groq alone, since an LLM judgment is more expressive than a statistical formula. The spec's requirement for a second, independent signal forced me to think about what Groq structurally *can't* see (surface variance, sentence rhythm, lexical diversity) and design a signal that fails in a complementary direction. That combination is what makes the "uncertain" band meaningful: it fires when the signals genuinely disagree, not just when confidence is arithmetically middling.

**One way my implementation diverged from the spec:** The spec describes the system as returning a `result` field in the `/submit` response. In my implementation, I renamed this field `attribution` and made it a label category string (`"likely_ai"`, `"uncertain"`, `"likely_human"`) rather than a raw score or verdict. I made this change because the raw confidence score is already returned in the `confidence` field, and a second numeric field named `result` would have been redundant and harder to consume. A label category string is more immediately actionable for a downstream platform — it can branch on `"likely_ai"` without parsing a float.

---

## AI Usage

**Instance 1 — Flask skeleton and stylometric signal**

I directed Claude to generate the initial Flask skeleton (`app.py`) with a `POST /submit` stub and a standalone `stylometric_score()` function implementing sentence length variance, type-token ratio, and punctuation density. Claude produced the function and the route structure. I then directed it to swap Signal 1 and Signal 2 (Groq and stylometry had been placed in the wrong order relative to my planning doc), and I modified the Groq prompt myself — adding specific calibration instructions ("use precise values like 0.63, not round numbers like 0.7") and a richer set of evidence criteria (word choice patterns, hedging language, personal details) that the original generated prompt had left vague.

**Instance 2 — Audit log schema and migration**

I directed Claude to build the SQLite audit log (`audit_log.py`) and specify the column schema. The initial generated schema was missing the `stylometric_score` column — it only captured `llm_score`. I directed Claude to add the missing column and implement a migration strategy so the existing `audit_log.db` (already populated from earlier testing) would not need to be dropped and recreated. Claude added an `ALTER TABLE ... ADD COLUMN` migration that runs on every connect and no-ops silently if the column already exists. I then reviewed the migration list and added `appeal_reasoning` to the same pattern when the appeals feature was added, rather than directing Claude to do it — I recognized the pattern and applied it myself.

---

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment — add your GROQ_API_KEY
cp .env.example .env

# Run the server
python app.py
```

**Dependencies:** Flask, Flask-Limiter, Groq SDK, python-dotenv
