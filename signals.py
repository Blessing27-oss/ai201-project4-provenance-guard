
"""
signals.py — Detection signal functions.

Each function takes raw text and returns a float in [0, 1],
where values closer to 1 indicate more AI-like characteristics.
"""

import re
import string


def stylometric_score(text: str) -> float:
    """
    Measures surface-level statistical uniformity in writing style.
    Returns a score in [0, 1] where 1 = highly AI-like uniformity.

    Three sub-signals, equally weighted:
      1. Sentence length variance  — low variance → AI-like
      2. Type-token ratio (TTR)    — low lexical diversity → AI-like
      3. Punctuation density variance — low variance across sentences → AI-like
    """
    sentences = _split_sentences(text)

    if len(sentences) < 2:
        # Not enough structure to measure variance meaningfully.
        return 0.5

    sentence_var_score = _sentence_length_score(sentences)
    ttr_score = _type_token_score(text)
    punct_score = _punctuation_variance_score(sentences)

    return round((sentence_var_score + ttr_score + punct_score) / 3.0, 4)


# ---------------------------------------------------------------------------
# Sub-signal helpers
# ---------------------------------------------------------------------------

def _sentence_length_score(sentences: list[str]) -> float:
    """
    Low variance in per-sentence word counts → score near 1 (AI-like).
    Uses a decay function: score = 1 / (1 + variance / SCALE).
    SCALE of 20 means a variance of 20 words² maps to a neutral 0.5.
    """
    SCALE = 20.0
    word_counts = [len(s.split()) for s in sentences]
    mean = sum(word_counts) / len(word_counts)
    variance = sum((wc - mean) ** 2 for wc in word_counts) / len(word_counts)
    return 1.0 / (1.0 + variance / SCALE)


def _type_token_score(text: str) -> float:
    """
    Low type-token ratio (fewer unique words relative to total) → score near 1.
    Score = 1 - TTR, so a TTR of 0.4 (low diversity) → score 0.6 (AI-like).
    """
    words = re.findall(r'\b\w+\b', text.lower())
    if not words:
        return 0.5
    ttr = len(set(words)) / len(words)
    return 1.0 - ttr


def _punctuation_variance_score(sentences: list[str]) -> float:
    """
    Low variance in punctuation density across sentences → score near 1 (AI-like).
    Punctuation density per sentence = punct_chars / total_chars.
    Uses the same decay: score = 1 / (1 + variance / SCALE).
    SCALE of 0.005 puts a typical AI-like variance near 0.5.
    """
    SCALE = 0.005
    punct_set = set(string.punctuation)

    densities = []
    for s in sentences:
        if not s:
            continue
        punct_count = sum(1 for c in s if c in punct_set)
        densities.append(punct_count / len(s))

    if len(densities) < 2:
        return 0.5

    mean = sum(densities) / len(densities)
    variance = sum((d - mean) ** 2 for d in densities) / len(densities)
    return 1.0 / (1.0 + variance / SCALE)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> list[str]:
    """Split on sentence-ending punctuation followed by whitespace."""
    raw = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in raw if s.strip()]
