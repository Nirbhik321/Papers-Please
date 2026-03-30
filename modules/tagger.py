"""
tagger.py — Generate 3-5 word topic labels for canonical question clusters.

Uses Ollama (local LLM) with Phi-3 Mini or any available model.
Falls back to simple keyword extraction if Ollama is unavailable.
Topic labels are generated once and cached in the DB — not re-generated
on every pipeline run.
"""

import re
import subprocess
from collections import Counter

# Try importing ollama; gracefully degrade if not installed
try:
    import ollama as _ollama
    _OLLAMA_AVAILABLE = True
except ImportError:
    _OLLAMA_AVAILABLE = False

# Preferred models in priority order
_PREFERRED_MODELS = ["phi3:mini", "phi3", "llama3.2:3b", "mistral:7b", "llama2"]


def _get_available_model() -> str | None:
    """Return the first available Ollama model from the preference list."""
    if not _OLLAMA_AVAILABLE:
        return None
    try:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=5
        )
        available = result.stdout.lower()
        for model in _PREFERRED_MODELS:
            if model.split(":")[0] in available:
                return model
    except Exception:
        pass
    return None


def generate_topic_label(question_texts: list[str]) -> str:
    """
    Generate a 3-5 word topic label for a group of semantically similar questions.

    Args:
        question_texts: list of paraphrases of the same question

    Returns:
        Topic label string, e.g. "CRC Encoder & Decoder"
    """
    model = _get_available_model()

    if model:
        return _label_with_ollama(question_texts, model)
    else:
        return _label_with_keywords(question_texts)


def _label_with_ollama(texts: list[str], model: str) -> str:
    """Use Ollama to generate a concise topic label."""
    sample = texts[:3]
    examples = "\n".join(f"- {t}" for t in sample)

    prompt = (
        "These are different phrasings of the same exam question:\n"
        f"{examples}\n\n"
        "Give me a 3-5 word topic label that captures what this question is about.\n"
        "Reply with ONLY the topic label — no explanation, no punctuation at end.\n"
        "Examples of good labels: 'CRC Encoder and Decoder', "
        "'TCP Three-Way Handshake', 'Dijkstra Shortest Path Algorithm'"
    )

    try:
        response = _ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1, "num_predict": 20},
        )
        label = response["message"]["content"].strip()
        # Sanitize: remove quotes, leading dashes, limit length
        label = re.sub(r"^[\-\*\"\'\s]+|[\"\'\s]+$", "", label)
        label = label[:60]
        return label if label else _label_with_keywords(texts)
    except Exception:
        return _label_with_keywords(texts)


# Stop words for keyword extraction fallback
_STOP_WORDS = {
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for",
    "with", "by", "from", "is", "are", "was", "be", "as", "its", "it",
    "that", "this", "which", "how", "what", "why", "when", "where",
    "explain", "define", "describe", "discuss", "derive", "prove", "show",
    "compare", "differentiate", "list", "write", "draw", "illustrate",
    "state", "evaluate", "analyze", "outline", "find", "solve", "give",
    "with", "neat", "brief", "short", "note", "detail", "example",
    "sketch", "diagram", "block", "using", "between",
}


def _label_with_keywords(texts: list[str]) -> str:
    """
    Fallback: extract most frequent meaningful words as a topic label.
    No LLM needed.
    """
    word_counts: Counter = Counter()
    for text in texts:
        words = re.findall(r"\b[a-zA-Z]{3,}\b", text)
        for w in words:
            w_lower = w.lower()
            if w_lower not in _STOP_WORDS:
                word_counts[w.title()] += 1

    top_words = [w for w, _ in word_counts.most_common(4)]
    if not top_words:
        return texts[0][:40] if texts else "Unknown Topic"
    return " ".join(top_words[:3])


def batch_generate_labels(canonicals: list[dict]) -> list[dict]:
    """
    Generate topic labels for all canonicals that don't already have one.
    Modifies canonicals in-place and returns the list.
    """
    model = _get_available_model()
    if model:
        print(f"  Generating topic labels with Ollama ({model})...")
    else:
        print("  Generating topic labels with keyword extraction (Ollama not available)...")

    for c in canonicals:
        if c.get("topic_label"):
            continue  # already labelled — skip
        texts = [a.get("text", "") for a in c.get("appearances", [])]
        texts = [t for t in texts if t]
        if not texts:
            texts = [c.get("representative_text", "")]
        c["topic_label"] = generate_topic_label(texts)

    return canonicals
