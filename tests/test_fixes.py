"""
tests/test_fixes.py — Smoke tests for the 5 solidification fixes.

Run with:
    python -m pytest tests/test_fixes.py -v
or directly:
    python tests/test_fixes.py
"""

import sys
import os
import re
import numpy as np

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Fix 1: OCR Preprocessing ──────────────────────────────────────────────────

def test_preprocess_increases_contrast():
    """_preprocess_for_ocr should increase std-deviation (contrast) on a flat image."""
    from modules.detector import _preprocess_for_ocr

    # Create a low-contrast synthetic image (narrow histogram around 128)
    rng = np.random.default_rng(42)
    gray = (128 + rng.normal(0, 8, (200, 400))).clip(0, 255).astype(np.uint8)

    std_before = gray.std()
    processed  = _preprocess_for_ocr(gray)
    std_after  = processed.std()

    assert std_after > std_before, (
        f"Expected contrast to increase after preprocessing. "
        f"std before={std_before:.2f}, std after={std_after:.2f}"
    )
    assert processed.dtype == np.uint8
    assert processed.shape == gray.shape
    print(f"  [PASS] OCR preprocessing: std {std_before:.2f} -> {std_after:.2f}")


# ── Fix 2: Keyword Fallback Labels ────────────────────────────────────────────

def test_keyword_label_no_verb_only():
    """Labels must not be a bare question verb like 'Explain'."""
    from modules.tagger import _label_with_keywords

    label = _label_with_keywords(["Explain CRC encoder operation"])
    assert label.lower() not in ("explain", "define", "describe", "discuss"), (
        f"Label is just a verb: '{label}'"
    )
    print(f"  [PASS] No bare verb: '{label}'")


def test_keyword_label_contains_topic():
    """CRC should be in the label when mentioned in multiple texts."""
    from modules.tagger import _label_with_keywords

    label = _label_with_keywords([
        "Explain CRC encoder operation",
        "Define CRC encoder and decoder",
    ])
    assert "CRC" in label.upper(), f"Expected 'CRC' in label, got: '{label}'"
    print(f"  [PASS] CRC in label: '{label}'")


def test_keyword_label_bigram():
    """Bigram extraction should prefer meaningful 2-word phrases."""
    from modules.tagger import _label_with_keywords

    label = _label_with_keywords(["TCP three way handshake mechanism"])
    assert "Three Way" in label or "TCP" in label or "Handshake" in label, (
        f"Expected bigram or TCP in label, got: '{label}'"
    )
    print(f"  [PASS] Bigram extracted: '{label}'")


# ── Fix 3: Module Header Detection ────────────────────────────────────────────

def test_module_header_strict():
    """Standard 'Module – 3' should be detected."""
    from modules.parser import _detect_module

    result = _detect_module([" ", " ", "Module - 3", "", ""], 2)
    assert result == 3, f"Expected 3, got {result}"
    print(f"  [PASS] Module - 3 detected as {result}")


def test_module_header_fuzzy2():
    """Garbled OCR 'Mfodwle =P 1' should be detected as module 1."""
    from modules.parser import _detect_module

    result = _detect_module(["", "", "Mfodwle =P 1", ""], 2)
    assert result == 1, f"Expected 1, got {result}"
    print(f"  [PASS] Fuzzy module header 'Mfodwle =P 1' detected as {result}")


def test_module_header_no_false_positive_qno():
    """A Q.No row like 'Q.3' must NOT fire as a module header."""
    from modules.parser import _detect_module

    result = _detect_module(["Q.3", "a", "Explain TCP protocol", "10", "L2"], 2)
    assert result is None, f"Expected None, got {result} (false positive on Q.No row)"
    print(f"  [PASS] Q.3 row not detected as module header")


def test_module_header_no_false_positive_marks():
    """A row with marks-range number (e.g. '10') must NOT fire as module 1."""
    from modules.parser import _detect_module

    result = _detect_module(["", "b", "Define CRC", "10"], 2)
    assert result is None, f"Expected None, got {result} (false positive on marks row)"
    print(f"  [PASS] Marks row '10' not detected as module header")


# ── Fix 4: Metadata Extraction ────────────────────────────────────────────────

def test_subject_code_non_bcs():
    """BAI501 (AI branch) should now be recognized."""
    from modules.detector import parse_filename_metadata

    meta = parse_filename_metadata("BAI501_JAN2025.pdf")
    assert meta["subject_code"] == "BAI501", (
        f"Expected BAI501, got {meta['subject_code']}"
    )
    assert meta["year"] == 2025
    print(f"  [PASS] BAI501 parsed: {meta}")


def test_subject_code_bee_prefix():
    """BEE654B (elective) should be recognized."""
    from modules.detector import parse_filename_metadata

    meta = parse_filename_metadata("BEE654B_2024.pdf")
    assert meta["subject_code"] == "BEE654B", (
        f"Expected BEE654B, got {meta['subject_code']}"
    )
    print(f"  [PASS] BEE654B parsed: {meta}")


def test_mqp_detection_filename():
    """'MQP' in filename should set exam_type='mqp'."""
    from modules.detector import parse_filename_metadata

    m1 = parse_filename_metadata("BCS502 MQP 2023.pdf")
    assert m1["exam_type"] == "mqp", f"Expected mqp, got {m1['exam_type']}"

    m2 = parse_filename_metadata("BCS502-model-paper-2024.pdf")
    assert m2["exam_type"] == "mqp", f"Expected mqp, got {m2['exam_type']}"

    m3 = parse_filename_metadata("BCS502 JAN 2024.pdf")
    assert m3["exam_type"] == "regular", f"Expected regular, got {m3['exam_type']}"

    print(f"  [PASS] MQP filename detection: mqp={m1['exam_type']}, model-paper={m2['exam_type']}, regular={m3['exam_type']}")


def test_mqp_detection_content():
    """'Model Question Paper' in content rows should set exam_type='mqp'."""
    from modules.detector import parse_content_metadata

    rows = [
        ["", "", "Fifth Semester B.E. Examination Dec 2024"],
        ["", "", "Model Question Paper"],
        ["", "", "Computer Networks"],
    ]
    meta = parse_content_metadata(rows)
    assert meta["exam_type"] == "mqp", f"Expected mqp, got {meta['exam_type']}"
    assert meta["year"] == 2024, f"Expected 2024, got {meta['year']}"
    print(f"  [PASS] Content MQP detection: exam_type={meta['exam_type']}, year={meta['year']}")


def test_content_metadata_all_branch_code():
    """Subject code regex should match non-BCS prefixes in content rows."""
    from modules.detector import parse_content_metadata

    rows = [
        ["", "", "Sixth Semester B.E. Examination Jan 2025"],
        ["", "", "BIS601"],
        ["", "", "Full Stack Development"],
    ]
    meta = parse_content_metadata(rows)
    assert meta["subject_code"] == "BIS601", f"Expected BIS601, got {meta['subject_code']}"
    print(f"  [PASS] Content subject code BIS601 extracted: {meta}")


# ── Fix 5: Graph Data Correctness ─────────────────────────────────────────────

def test_study_path_marking():
    """in_study_path should be True for nodes up to the full_coverage rank."""
    # Mock module_ladders as pipeline.get_module_analysis would return
    mock_ladders = {
        1: [
            {"frequency": 5, "frequency_pct": 1.0, "topic_label": "CRC Encoder",
             "representative_text": "Explain CRC encoder", "avg_marks": 10,
             "years": [2024, 2023], "appearances": [], "rank": 1,
             "full_coverage": False, "cumulative_expected": 10.0},
            {"frequency": 3, "frequency_pct": 0.6, "topic_label": "TCP Handshake",
             "representative_text": "Explain TCP handshake", "avg_marks": 10,
             "years": [2024], "appearances": [], "rank": 2,
             "full_coverage": True, "cumulative_expected": 16.0},
            {"frequency": 1, "frequency_pct": 0.2, "topic_label": "OSI Model",
             "representative_text": "Describe OSI model", "avg_marks": 10,
             "years": [2023], "appearances": [], "rank": 3,
             "full_coverage": True, "cumulative_expected": 18.0},
        ]
    }

    # Replicate the study_path_ids logic from 3_Graph.py
    study_path_ids: set = set()
    for module_no, steps in mock_ladders.items():
        coverage_cutoff = next(
            (s["rank"] for s in steps if s.get("full_coverage")), len(steps)
        )
        for step in steps[:coverage_cutoff]:
            study_path_ids.add((module_no, step.get("rank", 1)))

    assert (1, 1) in study_path_ids, "Rank-1 node should be in study path"
    assert (1, 2) in study_path_ids, "Rank-2 node (first full_coverage) should be in study path"
    assert (1, 3) not in study_path_ids, "Rank-3 node should NOT be in study path"
    print(f"  [PASS] Study path IDs: {study_path_ids}")


def test_frequency_filter():
    """Nodes below min_freq should be excluded from graph."""
    mock_steps = [
        {"frequency": 3, "frequency_pct": 0.6, "rank": 1, "full_coverage": False,
         "cumulative_expected": 6.0, "avg_marks": 10, "years": [2024],
         "appearances": [], "topic_label": "CRC", "representative_text": "CRC"},
        {"frequency": 1, "frequency_pct": 0.2, "rank": 2, "full_coverage": True,
         "cumulative_expected": 8.0, "avg_marks": 10, "years": [2024],
         "appearances": [], "topic_label": "OSI", "representative_text": "OSI"},
    ]

    min_freq = 2
    visible = [s for s in mock_steps if s["frequency"] >= min_freq]
    assert len(visible) == 1, f"Expected 1 visible node at min_freq=2, got {len(visible)}"
    assert visible[0]["topic_label"] == "CRC"
    print(f"  [PASS] Frequency filter: {len(visible)}/2 nodes visible at min_freq={min_freq}")


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_preprocess_increases_contrast,
        test_keyword_label_no_verb_only,
        test_keyword_label_contains_topic,
        test_keyword_label_bigram,
        test_module_header_strict,
        test_module_header_fuzzy2,
        test_module_header_no_false_positive_qno,
        test_module_header_no_false_positive_marks,
        test_subject_code_non_bcs,
        test_subject_code_bee_prefix,
        test_mqp_detection_filename,
        test_mqp_detection_content,
        test_content_metadata_all_branch_code,
        test_study_path_marking,
        test_frequency_filter,
    ]

    passed = 0
    failed = 0
    for t in tests:
        name = t.__name__
        try:
            t()
            passed += 1
        except Exception as exc:
            failed += 1
            print(f"  [FAIL] {name}: {exc}")

    print(f"\n{'='*55}")
    print(f"  Results: {passed}/{passed+failed} passed, {failed} failed")
    print(f"{'='*55}")
    if failed:
        sys.exit(1)
