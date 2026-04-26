"""
pipeline.py — 7-step orchestrator.

Steps:
  1. detect_and_extract  — native or scanned table extraction
  2. parse_rows          — table rows → sub_question records
  3. save_to_db          — papers + sub_questions into SQLite
  4. deduplicate         — module-level semantic grouping
  5. score_and_rank      — frequency × recency × marks
  6. tag_topics          — Ollama topic labels (new canonicals only)
  7. persist_canonicals  — write canonical_questions + appearances to DB

Run via pipeline.run(pdf_paths, db_path) from Streamlit or CLI.
"""

import json
from pathlib import Path

from modules import db, detector, parser, deduplicator, scorer, tagger


def run(
    pdf_paths: list[str],
    db_path: str,
    force: bool = False,
    progress_callback=None,
) -> dict:
    """
    Process a list of PDF paths end-to-end.

    Args:
        pdf_paths: absolute paths to uploaded PDFs
        db_path: SQLite database path
        force: re-process even if PDF already in DB
        progress_callback: optional callable(step: str, pct: float)

    Returns:
        Summary dict with keys: papers_added, sub_questions_added,
                                 subjects_processed, errors
    """
    db.init_db(db_path)
    cache_dir = Path(db_path).parent / "extracted"
    cache_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "papers_added": 0,
        "sub_questions_added": 0,
        "subjects_processed": set(),
        "errors": [],
    }

    def _progress(msg: str, pct: float = 0.0):
        print(f"  [{pct:3.0f}%] {msg}")
        if progress_callback:
            progress_callback(msg, pct)

    # ── Steps 1–3: Extract and store each PDF ──────────────────────────────────
    for idx, pdf_path in enumerate(pdf_paths):
        pdf_path = str(pdf_path)
        fname = Path(pdf_path).name
        base_pct = idx / max(len(pdf_paths), 1) * 60  # steps 1-3 use 0-60%

        _progress(f"Processing {fname}", base_pct)

        # Skip if already in DB (unless forced)
        if not force and db.paper_exists(db_path, fname):
            _progress(f"  Skipping {fname} (already in DB)", base_pct)
            continue

        # Step 1 — Extract table
        _progress(f"  Reading {fname}...", base_pct + 5)
        try:
            pdf_type, raw_rows = detector.detect_and_extract(pdf_path)
        except Exception as e:
            summary["errors"].append(
                f"{fname}: could not read PDF — {type(e).__name__}. "
                "Check the file is a valid PDF and not password-protected."
            )
            continue

        _progress(f"  Extracted {len(raw_rows)} rows from {fname}", base_pct + 10)

        # Metadata: merge filename hints with content parsed from the PDF itself
        filename_meta = detector.parse_filename_metadata(fname)
        content_meta  = detector.parse_content_metadata(raw_rows)

        def _best(a, b, bad=("UNKNOWN", None, "")):
            """Return a if it's valid, else b."""
            return a if a not in bad else b

        meta = {
            "subject_code": _best(filename_meta["subject_code"], content_meta["subject_code"], ("UNKNOWN", None, "")),
            "subject_name": _best(filename_meta["subject_name"], content_meta["subject_name"], ("UNKNOWN", None, "")),
            "month":        filename_meta["month"] or content_meta["month"],
            "year":         filename_meta["year"]  or content_meta["year"],
        }
        # Final fallback: if name is still unset, use subject code as name
        if not meta["subject_name"] or meta["subject_name"] == meta["subject_code"]:
            if content_meta["subject_name"]:
                meta["subject_name"] = content_meta["subject_name"]
            elif meta["subject_code"] and meta["subject_code"] != "UNKNOWN":
                meta["subject_name"] = meta["subject_code"]

        if meta["subject_code"] == "UNKNOWN":
            summary["errors"].append(
                f"{fname}: subject could not be identified from filename or PDF content. "
                "Rename the file to include the subject code (e.g. 'JAN 2025 BCS502.pdf') and re-upload."
            )
            continue

        # Cache raw rows for debugging
        cache_file = cache_dir / (fname.rsplit(".", 1)[0] + ".json")
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({"pdf_type": pdf_type, "rows": raw_rows}, f, indent=2, ensure_ascii=False)
        except Exception:
            pass  # cache write failure is non-fatal

        # Step 2 — Parse rows into sub_question records
        try:
            sub_qs = parser.parse_rows(raw_rows)
        except Exception as e:
            summary["errors"].append(
                f"{fname}: question extraction failed — {type(e).__name__}. "
                "The PDF layout may be unusual."
            )
            continue

        _progress(f"  Found {len(sub_qs)} questions in {fname}", base_pct + 15)

        if not sub_qs:
            summary["errors"].append(
                f"{fname}: no questions could be extracted. "
                "The PDF may be low quality or use an unsupported layout."
            )
            continue

        # Step 3 — Save to DB
        try:
            paper_id = db.insert_paper(db_path, {**meta, "filename": fname, "pdf_type": pdf_type})
            if paper_id is None:
                _progress(f"  {fname} already in database — skipping")
                continue
            if force:
                db.delete_sub_questions_for_paper(db_path, paper_id)
            db.insert_sub_questions(db_path, paper_id, sub_qs)
        except Exception as e:
            summary["errors"].append(
                f"{fname}: database error — {type(e).__name__}. Try re-uploading."
            )
            continue

        summary["papers_added"] += 1
        summary["sub_questions_added"] += len(sub_qs)
        summary["subjects_processed"].add(meta["subject_code"])
        _progress(f"  Saved {fname} ({meta['subject_code']})", base_pct + 20)

    # ── Steps 4–7: Analyse each affected subject ───────────────────────────────
    affected_subjects = summary["subjects_processed"]
    if not affected_subjects:
        # No new papers — re-analyse all existing subjects anyway
        for row in db.get_all_papers(db_path):
            affected_subjects.add(row["subject_code"])

    total_subjects = max(len(affected_subjects), 1)
    for subj_idx, subject_code in enumerate(affected_subjects):
        subj_base_pct = 60 + (subj_idx / total_subjects) * 40

        _progress(f"Analysing {subject_code}...", subj_base_pct)

        try:
            # Count total papers for this subject
            all_papers = [p for p in db.get_all_papers(db_path)
                          if p["subject_code"] == subject_code]
            total_papers = len(all_papers)

            # Clear old canonicals so we do a clean re-dedup
            db.delete_canonicals_for_subject(db_path, subject_code)

            # Process each module
            for module_no in range(1, 6):
                sub_qs_for_module = db.get_sub_questions_for_module(
                    db_path, subject_code, module_no
                )
                if not sub_qs_for_module:
                    continue

                _progress(
                    f"  {subject_code} Module {module_no}: grouping questions...",
                    subj_base_pct + module_no * 4,
                )

                # Step 4 — Deduplicate
                canonicals = deduplicator.deduplicate(sub_qs_for_module)

                # Step 5 — Score
                scored = scorer.score_canonicals(canonicals, total_papers)

                # Step 6 — Tag topics (Ollama or keyword fallback)
                scored = tagger.batch_generate_labels(scored)

                # Step 7 — Persist
                for c in scored:
                    canonical_id = db.upsert_canonical(db_path, {
                        "subject_code": subject_code,
                        "module_no": module_no,
                        "representative_text": c["representative_text"],
                        "topic_label": c.get("topic_label"),
                        "avg_marks": c.get("avg_marks"),
                        "frequency": c.get("frequency", 0),
                        "weighted_score": c.get("weighted_score", 0.0),
                        "last_seen_year": c.get("last_seen_year"),
                    })

                    for appearance in c.get("appearances", []):
                        db.insert_appearance(db_path, {
                            "canonical_id": canonical_id,
                            "sub_question_id": appearance["sub_question_id"],
                            "paper_id": appearance["paper_id"],
                            "year": appearance.get("year"),
                            "q_no": appearance.get("q_no"),
                            "sub_q": appearance.get("sub_q"),
                            "marks": appearance.get("marks"),
                        })

        except Exception as e:
            summary["errors"].append(
                f"Analysis failed for {subject_code}: {type(e).__name__} — {e}"
            )

    summary["subjects_processed"] = list(summary["subjects_processed"])
    _progress("Done.", 100)
    return summary


def get_module_analysis(
    db_path: str,
    subject_code: str,
) -> dict[int, list[dict]]:
    """
    Return the marks ladder for every module of a subject.
    Used by the Streamlit dashboard and PDF exporter.

    Returns: {module_no: [step, ...]}
    """
    db.init_db(db_path)
    all_papers = [p for p in db.get_all_papers(db_path)
                  if p["subject_code"] == subject_code]
    total_papers = len(all_papers)

    result: dict[int, list[dict]] = {}

    for module_no in range(1, 6):
        canonicals = db.get_canonicals_for_module(db_path, subject_code, module_no)
        if not canonicals:
            continue

        # Rehydrate with appearances for formatter functions
        enriched = []
        for c in canonicals:
            appearances = db.get_appearances_for_canonical(db_path, c["id"])
            enriched.append({
                **c,
                "appearances": appearances,
                "frequency_pct": c["frequency"] / max(total_papers, 1),
                "expected_marks": (c["frequency"] / max(total_papers, 1)) * (c["avg_marks"] or 0),
                "years": sorted(
                    {a["year"] for a in appearances if a.get("year")}, reverse=True
                ),
            })

        # With only 1 paper, frequency is meaningless — rank by marks instead
        if total_papers == 1:
            enriched.sort(key=lambda x: x.get("avg_marks") or 0, reverse=True)
        else:
            enriched.sort(key=lambda x: x["weighted_score"], reverse=True)

        result[module_no] = scorer.build_marks_ladder(enriched, max_marks=20)

    return result, total_papers
