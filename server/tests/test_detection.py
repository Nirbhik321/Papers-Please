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
