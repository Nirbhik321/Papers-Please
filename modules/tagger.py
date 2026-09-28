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


# Instruction words that open exam questions ("Explain the …", "What is …")
_LEADING = re.compile(
    r"^(?:"
    r"(?:what|which|how|why|when)\s+(?:is\s+meant\s+by|is|are|do|does|are\s+the|is\s+the)\s+"
    r"|(?:briefly|clearly|neatly)\s+"
    r"|(?:explain|define|describe|discuss|derive|prove|show|compare|contrast|differentiate|distinguish|"
    r"list|write|draw|illustrate|state|evaluate|analy[sz]e|outline|find|solve|give|mention|enumerate|"
    r"elaborate|sketch|construct|design|develop|obtain|calculate|compute|determine|identify|demonstrate|"
    r"justify|apply|implement|summari[sz]e)(?:\s+|$)(?:and\s+(?:explain|describe|discuss)\s+|out\s+|down\s+)?"
    r"|(?:a|an|the|about|in\s+brief|in\s+detail|short\s+notes?\s+on|notes?\s+on|(?:the\s+)?following|"
    r"between|different|various|any\s+(?:two|three|four))(?:\s+|$)"
    r")+",
    re.IGNORECASE,
)
_WITH_DIAGRAM = re.compile(
    r"\bwith\s+(?:a\s+|an\s+)?(?:neat\s+|suitable\s+|relevant\s+|clear\s+)?(?:block\s+|labell?ed\s+)?"
    r"(?:diagrams?|sketch(?:es)?|examples?|figures?)\b\s*,?\s*",
    re.IGNORECASE,
)
_LIST_MARKER = re.compile(r"(?<![A-Za-z])(?:[a-d]|i{1,3}|iv)\)\s*", re.IGNORECASE)
_TRAILING = re.compile(r"\s+(?:in\s+detail|in\s+brief|briefly|neatly|in\s+short)$", re.IGNORECASE)
_CLAUSE_SPLIT = re.compile(r"[?.;:]\s*|,\s*|\s+(?:with|using|for\s+the\s+given|by\s+taking)\s+", re.IGNORECASE)
_SUB_LABEL = re.compile(r"^[a-cA-C][.)]\s+")
_WELL_FORMED = re.compile(
    r"^(?:what|which|how|why|explain|define|describe|discuss|derive|compare|differentiate|distinguish|"
    r"list|write|draw|illustrate|state|briefly|give|find|solve|design|develop|construct)\b",
    re.IGNORECASE,
)
_SMALL = {"of", "and", "in", "for", "to", "on", "the", "a", "an", "vs", "or", "with", "by", "at"}


def _titlecase(words: list[str]) -> str:
    out = []
    for i, w in enumerate(words):
        if any(c.isdigit() for c in w) or "/" in w or (w.isupper() and len(w) > 1):
            out.append(w)                       # TCP/IP, IPv4, CRC stay as written
        elif i > 0 and w.lower() in _SMALL:
            out.append(w.lower())
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


def _label_from_phrase(texts: list[str]) -> str | None:
    """
    Fallback: pull the subject of the question out of its shortest wording —
    "What is data communication? List …" → "Data Communication".
    """
    # Prefer well-formed questions ("Describe …") over OCR fragments, then the shortest
    cleaned = [_SUB_LABEL.sub("", t.strip()) for t in texts]
    candidates = sorted((t for t in cleaned if len(t) >= 12),
                        key=lambda t: (0 if _WELL_FORMED.match(t) else 1, len(t))) or cleaned
    for text in candidates[:3]:
        text = _LIST_MARKER.sub(" ", _WITH_DIAGRAM.sub("", text))
        for clause in _CLAUSE_SPLIT.split(text):
            clause = _TRAILING.sub("", _LEADING.sub("", clause.strip())).strip(" -()'\"")
            words = [w.strip("()'\"") for w in clause.split()]
            words = [w for w in words if w]
            if len(words) >= 1 and len(" ".join(words)) >= 3:
                words = words[:6]
                while words and words[-1].lower() in _SMALL:
                    words.pop()
                if words:
                    return _titlecase(words)
    return None


def _label_with_keywords(texts: list[str]) -> str:
    """
    Fallback: a phrase taken from the question itself, or failing that the
    most frequent meaningful words. No LLM needed.
    """
    phrase = _label_from_phrase(texts)
    if phrase:
        return phrase
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
