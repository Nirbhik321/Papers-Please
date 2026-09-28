"""
tagger.py — Generate 3-5 word topic labels for canonical question clusters.

Uses Ollama (local LLM) via direct HTTP REST call — no pydantic dependency.
Falls back to bigram-based keyword extraction if Ollama is unavailable.
Topic labels are generated once and cached in the DB — not re-generated
on every pipeline run.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from collections import Counter

# 127.0.0.1, not localhost: on Windows "localhost" tries ::1 first and a refused
# connection costs ~1 s per address. OLLAMA_URL="" turns the LLM tier off entirely.
_OLLAMA_BASE = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
_PROBE_TTL_S = 300
_probe: tuple[float, str | None] | None = None   # (checked_at, model): one probe per 5 min, not per label

# Preferred models in priority order
_PREFERRED_MODELS = ["phi3:mini", "phi3", "llama3.2:3b", "mistral:7b", "llama2", "llama3.2"]


def _get_available_model() -> str | None:
    """
    Return the first installed Ollama model that matches our preference list.
    Uses the REST API directly — no pydantic/ollama package required. The answer
    is cached, because a subject rebuild labels dozens of topics in a row.
    """
    global _probe
    if not _OLLAMA_BASE:
        return None
    now = time.monotonic()
    if _probe and now - _probe[0] < _PROBE_TTL_S:
        return _probe[1]
    model = None
    try:
        with urllib.request.urlopen(f"{_OLLAMA_BASE}/api/tags", timeout=1) as req:
            data = json.loads(req.read().decode())
        installed = [m["name"] for m in data.get("models", [])]
        # Match against preference list by base name
        for preferred in _PREFERRED_MODELS:
            prefix = preferred.split(":")[0]
            model = next((a for a in installed if a.split(":")[0] == prefix), None)
            if model:
                break
    except Exception:
        pass
    _probe = (now, model)
    return model


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
    """Use Ollama REST API to generate a concise topic label."""
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
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 20},
        }).encode()

        req = urllib.request.Request(
            f"{_OLLAMA_BASE}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())

        label = result.get("message", {}).get("content", "").strip()
        # Sanitize: remove quotes, leading dashes, limit length
        label = re.sub(r"^[\-\*\"\'\s]+|[\"\'\s]+$", "", label)
        # Strip leading question verbs if model ignored the instruction
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
    Fallback when no LLM is available: a phrase taken from the question itself
    ("What is data communication? List …" → "Data Communication"), or failing
    that the most frequent meaningful unigrams and bigrams.

    Strategy:
    1. Collect candidate words (unigrams, 3+ chars, not in stop list).
    2. Build bigrams from adjacent non-stop words in the same sentence.
    3. Score bigrams × 2 vs unigrams × 1; pick top candidates.
    4. Return "Word1 Word2" or "Word1 & Word2" for co-equal leaders.
    """
    phrase = _label_from_phrase(texts)
    if phrase:
        return phrase

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
