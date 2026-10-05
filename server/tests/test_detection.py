"""Subject-code and session detection from filenames and scanned headers."""

from modules.detector import find_subject_code, parse_content_metadata, parse_filename_metadata


def test_codes_for_every_branch():
    for name, code in [("JAN 2025 BCS502.pdf", "BCS502"), ("JAN_2025_BCS502.pdf", "BCS502"),
                       ("BIS601 june 2024.pdf", "BIS601"), ("bai515b Dec 2024.pdf", "BAI515B"),
                       ("BESCK104A-2024.pdf", "BESCK104A")]:
        assert parse_filename_metadata(name)["subject_code"] == code


def test_ocr_misread_codes_map_back_only_to_real_subjects():
    assert find_subject_code("\\ BCSS02 | USN") == "BCS502"
    assert find_subject_code("8CS5O2") == "BCS502"
    assert find_subject_code("B.E. Examination 2025") is None


def test_ambiguous_subject_name_does_not_guess_a_branch():
    # "Computer Networks" exists as BCS502, BAD502, ... — the name alone mustn't pick one
    meta = parse_content_metadata([["B.E. Examination, June/July 2025"], ["Computer Networks"]])
    assert meta["subject_code"] is None and meta["subject_name"] == "Computer Networks"


def test_explicit_code_beats_name():
    meta = parse_content_metadata([["BCSS02"], ["B.E. Examination, Dec.2024/Jan.2025"], ["Computer Networks"]])
    assert meta["subject_code"] == "BCS502" and meta["year"] == 2025


def test_native_pdf_header_is_read_for_metadata():
    import pytest
    from pathlib import Path
    from modules.detector import header_rows, parse_content_metadata
    pdf = Path(__file__).resolve().parents[2] / "data" / "raw" / "MQP 2.pdf"
    if not pdf.exists():
        pytest.skip("sample paper not available")
    meta = parse_content_metadata(header_rows(str(pdf)))
    assert meta["subject_code"] == "BCS502" and meta["exam_type"] == "mqp"


def test_stray_ocr_letter_maps_to_the_real_code():
    assert find_subject_code("BCSS501 | USN") == "BCS501"
    assert find_subject_code("BXYZ999") == "BXYZ999"      # unknown but well-formed: kept for review
    assert find_subject_code("BAD502 and BCS502") == "BAD502"


def test_month_joined_to_year_in_filename():
    from server import catalog
    meta = parse_filename_metadata("BCS502_Dec2024.pdf")
    assert (meta["month"], meta["year"]) == ("December", 2024)
    # the Dec 2024 / Jan 2025 session, not January 2024
    assert catalog.normalize_session(meta["month"], meta["year"]) == ("January", 2025)
    assert parse_filename_metadata("BCS502-Nov2024.pdf")["month"] == "November"
    assert parse_filename_metadata("JuneJuly_2025.pdf")["month"] is None       # run-together: leave to content
    assert parse_filename_metadata("Marks Mayank BCS502 2024.pdf")["month"] is None


def test_both_grouping_methods_merge_paraphrases_and_keep_others_apart():
    import numpy as np
    from modules.deduplicator import deduplicate
    texts = ["Explain the CRC encoder and decoder with an example.",
             "Describe the CRC encoder and decoder with a neat diagram.",
             "Explain the TCP three-way handshake."]
    qs = [{"id": i, "text": t, "marks": 10, "year": 2025, "paper_id": i, "q_no": 1, "sub_q": "a"} for i, t in enumerate(texts)]
    vecs = {texts[0]: [1.0, 0.0], texts[1]: [0.96, 0.28], texts[2]: [0.0, 1.0]}
    encode = lambda ts: np.array([vecs.get(t, [0.0, 1.0]) for t in ts], dtype=np.float32)
    for method in ("average", "greedy"):
        groups = sorted(sorted(a["sub_question_id"] for a in c["appearances"])
                        for c in deduplicate(qs, threshold=0.725, encode=encode, method=method))
        assert groups == [[0, 1], [2]], (method, groups)
