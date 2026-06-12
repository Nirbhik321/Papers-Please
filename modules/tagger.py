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
        "Give me a 3-5 word topic label that names the CONCEPT this question is about.\n"
        "Rules: do NOT start with a question verb (explain / define / describe / discuss / derive).\n"
        "Reply with ONLY the topic label — no explanation, no punctuation at end.\n"
        "Examples of good labels: 'CRC Encoder and Decoder', "
        "'TCP Three-Way Handshake', 'Dijkstra Shortest Path Algorithm', "
        "'OSI Reference Model', 'Pipelining Hazards'"
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
        # Strip leading question verbs if Ollama ignored the instruction
        label = re.sub(
            r"^(Explain|Define|Describe|Discuss|Derive|Prove|Show|Compare|List|Write|Draw|Illustrate|State|Evaluate|Analyze|Outline|Find|Solve|Give)\s+",
            "",
            label,
            flags=re.IGNORECASE,
        )
        label = label[:60]
        return label if label else _label_with_keywords(texts)
    except Exception:
        return _label_with_keywords(texts)


# Stop words for keyword extraction fallback
_STOP_WORDS = {
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for",
    "with", "by", "from", "is", "are", "was", "be", "as", "its", "it",
    "that", "this", "which", "how", "what", "why", "when", "where",
    # VTU question-verb junk
    "explain", "define", "describe", "discuss", "derive", "prove", "show",
    "compare", "differentiate", "list", "write", "draw", "illustrate",
    "state", "evaluate", "analyze", "analyse", "outline", "find", "solve",
    "give", "obtain", "determine", "compute", "calculate",
    # Exam boilerplate
    "neat", "brief", "short", "note", "detail", "example", "suitable",
    "sketch", "diagram", "block", "using", "between", "following", "hence",
    "also", "following", "necessary", "clearly", "important",
}


def _to_display(word: str) -> str:
    """
    Convert a raw token to its display form.
    Preserves ALL-CAPS acronyms (e.g., CRC, TCP, OSI) and title-cases others.
    """
    if word.isupper() and len(word) >= 2:
        return word  # keep acronyms as-is
    return word.title()


def _label_with_keywords(texts: list[str]) -> str:
    """
    Fallback: extract most-frequent meaningful unigrams and bigrams as a topic label.

    Strategy:
    1. Collect candidate words (unigrams, 3+ chars, not in stop list).
    2. Build bigrams from adjacent non-stop words in the same sentence.
    3. Score bigrams × 2 vs unigrams × 1; pick top candidates.
    4. Return "Word1 Word2" or "Word1 & Word2" for co-equal leaders.
    """
    unigram_counts: Counter = Counter()
    bigram_counts: Counter = Counter()

    for text in texts:
        # Tokenise: words only (strip punctuation)
        words = re.findall(r"\b[a-zA-Z]{3,}\b", text)
        # Filter stop words but preserve original casing for display
        filtered = [(w, w.lower()) for w in words if w.lower() not in _STOP_WORDS]

        for orig, low in filtered:
            unigram_counts[_to_display(orig)] += 1

        # Consecutive non-stop pairs → bigrams
        for i in range(len(filtered) - 1):
            orig_a, low_a = filtered[i]
            orig_b, low_b = filtered[i + 1]
            bigram = f"{_to_display(orig_a)} {_to_display(orig_b)}"
            bigram_counts[bigram] += 1

    if not unigram_counts:
        return texts[0][:40] if texts else "Unknown Topic"

    # Merge: each bigram occurrence counts double
    combined: Counter = Counter()
    for w, c in unigram_counts.items():
        combined[w] += c
    for bg, c in bigram_counts.items():
        combined[bg] += c * 2

    # Pick top tokens; prefer longer (bigram) tokens at equal score
    top = sorted(combined.items(), key=lambda x: (-x[1], -len(x[0])))
    top_tokens = [tok for tok, _ in top[:3]]

    # If top two are single words that appear together as a bigram, merge them
    if len(top_tokens) >= 2:
        merged = f"{top_tokens[0]} {top_tokens[1]}"
        if merged in bigram_counts or f"{_to_display(top_tokens[0])} {_to_display(top_tokens[1])}" in bigram_counts:
            return merged

    if len(top_tokens) >= 2 and top[0][1] == top[1][1]:
        return f"{top_tokens[0]} & {top_tokens[1]}"

    return top_tokens[0] if top_tokens else (texts[0][:40] if texts else "Unknown Topic")


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
