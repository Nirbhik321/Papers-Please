"""
The experiments behind every number in the paper.

  extraction_eval   system-extracted questions vs hand transcriptions
  grouping_eval     same-meaning grouping vs hand-labelled groups: models × thresholds × algorithms,
                    with leave-one-subject-out threshold selection
  backtest          rank topics from older papers only, then measure the marks a student would
                    secure in the *next* exam by studying the top-k topics per module
  perf              timings and memory
"""

import random
import re
import statistics
import time
from collections import Counter, defaultdict

import numpy as np

from eval import embedders
from eval.common import load_gt_groups, load_gt_papers, load_system, qref, session_label, session_order
from eval.metrics import bcubed, match_questions, pair_counts, prf

MODULE_MARKS = 20


# ── Data assembly ──────────────────────────────────────────────────────────────

def gt_items(gt: dict[str, dict]) -> list[dict]:
    """Every hand-transcribed sub-question as a flat record."""
    items = []
    for pid, paper in gt.items():
        for q in paper["questions"]:
            items.append({
                "ref": qref(pid, q), "paper_id": pid, "subject": paper["subject_code"],
                "module": q["module"], "q_no": q["q_no"], "sub_q": q["sub_q"],
                "marks": q.get("marks"), "text": q["text"], "year": paper.get("exam_year"),
                "paper_type": paper.get("paper_type"),
            })
    return items


def group_map(groups: dict[str, dict]) -> dict[str, str]:
    """question ref → group id."""
    out = {}
    for subject, g in groups.items():
        for i, grp in enumerate(g["groups"]):
            for ref in grp["members"]:
                out[ref] = f"{subject}#{i}"
    return out


def duplicate_scans(gt: dict[str, dict], gmap: dict[str, str]) -> dict[str, str]:
    """
    Papers that are another copy of the same exam (same subject + session, and most
    questions in the same groups). Returns {duplicate_id: kept_id}.
    """
    dups = {}
    by_session = defaultdict(list)
    for pid, p in gt.items():
        if p.get("paper_type") == "see" and p.get("exam_year"):
            by_session[(p["subject_code"], p["exam_year"], p.get("exam_month"))].append(pid)
    for pids in by_session.values():
        pids.sort(key=lambda x: -len(gt[x]["questions"]))
        keep = pids[0]
        keep_groups = {gmap.get(qref(keep, q)) for q in gt[keep]["questions"]}
        for other in pids[1:]:
            other_groups = [gmap.get(qref(other, q)) for q in gt[other]["questions"]]
            if other_groups and sum(g in keep_groups for g in other_groups) / len(other_groups) >= 0.6:
                dups[other] = keep
    return dups


# ── 1. Extraction ──────────────────────────────────────────────────────────────

def extraction_eval(gt: dict[str, dict], system: dict[str, dict]) -> dict:
    per_paper, totals = [], defaultdict(Counter)
    for pid, paper in gt.items():
        if pid not in system:
            continue
        sys_qs = [q for q in system[pid]["sub_questions"] if 1 <= q["module_no"] <= 5]
        gold = paper["questions"]
        pairs, miss_g, extra_s = match_questions(gold, sys_qs)
        module_ok = sum(gold[i]["module"] == sys_qs[j]["module_no"] for i, j, _ in pairs)
        label_ok = sum(gold[i]["q_no"] == sys_qs[j]["q_no"] and gold[i]["sub_q"] == sys_qs[j]["sub_q"] for i, j, _ in pairs)
        marks_gold = [(i, j) for i, j, _ in pairs if gold[i].get("marks")]
        marks_ok = sum(gold[i]["marks"] == sys_qs[j].get("marks") for i, j in marks_gold)
        sims = [s for _, _, s in pairs]
        kind = system[pid]["pdf_type"]
        row = {
            "paper_id": pid, "pdf_type": kind, "gold": len(gold), "extracted": len(sys_qs),
            **{k: v for k, v in prf(len(pairs), len(extra_s), len(miss_g)).items()},
            "module_acc": module_ok / len(pairs) if pairs else 0.0,
            "label_acc": label_ok / len(pairs) if pairs else 0.0,
            "marks_acc": marks_ok / len(marks_gold) if marks_gold else 0.0,
            "text_sim": statistics.mean(sims) if sims else 0.0,
            "seconds": system[pid].get("seconds"), "pages": system[pid].get("page_count"),
        }
        per_paper.append(row)
        for key in (kind, "all"):
            t = totals[key]
            t["papers"] += 1
            t["gold"] += len(gold)
            t["extracted"] += len(sys_qs)
            t["tp"] += len(pairs)
            t["fp"] += len(extra_s)
            t["fn"] += len(miss_g)
            t["module_ok"] += module_ok
            t["label_ok"] += label_ok
            t["marks_ok"] += marks_ok
            t["marks_n"] += len(marks_gold)
            t["sim_sum"] += sum(sims)
    summary = {}
    for key, t in totals.items():
        summary[key] = {
            "papers": t["papers"], "gold": t["gold"], "extracted": t["extracted"],
            **prf(t["tp"], t["fp"], t["fn"]),
            "module_acc": t["module_ok"] / t["tp"] if t["tp"] else 0.0,
            "label_acc": t["label_ok"] / t["tp"] if t["tp"] else 0.0,
            "marks_acc": t["marks_ok"] / t["marks_n"] if t["marks_n"] else 0.0,
            "text_sim": t["sim_sum"] / t["tp"] if t["tp"] else 0.0,
        }
    return {"per_paper": per_paper, "summary": summary}


# ── 2. Grouping ────────────────────────────────────────────────────────────────

_BOILERPLATE = re.compile(
    r"\b(with\s+(a\s+)?(neat|suitable|relevant|clear)?\s*(block\s+)?(diagram|sketch|example|figure)s?|"
    r"in\s+detail|in\s+brief|briefly|neatly|with\s+examples?|using\s+suitable\s+examples?|"
    r"explain|describe|discuss|illustrate|define|write\s+(short\s+)?notes?\s+on|write|list|"
    r"what\s+(is|are)|how|elaborate|outline|summari[sz]e|demonstrate|the|a|an)\b",
    re.IGNORECASE,
)


def focus_text(text: str) -> str:
    """The subject of a question with instruction words and 'with a neat diagram' removed."""
    t = _BOILERPLATE.sub(" ", text)
    t = re.sub(r"[^A-Za-z0-9/+\-' ]+", " ", t)
    t = " ".join(t.split())
    return t if len(t) >= 12 else text


def cluster_greedy(items: list[dict], enc, threshold: float, variant: str) -> dict[str, int]:
    """The original production algorithm (deduplicator, method="greedy"), module by module."""
    from modules.deduplicator import deduplicate
    labels, next_id = {}, 0
    by_module = defaultdict(list)
    for it in items:
        by_module[(it["subject"], it["module"])].append(it)
    for (_, _), its in sorted(by_module.items()):
        recs = [{"id": it["ref"], "text": it["text"] if variant == "raw" else focus_text(it["text"]),
                 "marks": it["marks"], "year": it["year"], "paper_id": it["paper_id"],
                 "q_no": it["q_no"], "sub_q": it["sub_q"]} for it in its]
        for canon in deduplicate(recs, threshold=threshold, encode=enc.encode, method="greedy"):
            for a in canon["appearances"]:
                labels[a["sub_question_id"]] = next_id
            next_id += 1
        for it in its:                       # very short texts are dropped by deduplicate → singletons
            if it["ref"] not in labels:
                labels[it["ref"]] = next_id
                next_id += 1
    return labels


def cluster_agglomerative(items: list[dict], enc, threshold: float, variant: str, linkage: str) -> dict[str, int]:
    from sklearn.cluster import AgglomerativeClustering
    labels, offset = {}, 0
    by_module = defaultdict(list)
    for it in items:
        by_module[(it["subject"], it["module"])].append(it)
    for _, its in sorted(by_module.items()):
        texts = [it["text"] if variant == "raw" else focus_text(it["text"]) for it in its]
        if len(its) == 1:
            labels[its[0]["ref"]] = offset
            offset += 1
            continue
        X = enc.encode(texts)
        model = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage=linkage,
                                        distance_threshold=1 - threshold)
        lab = model.fit_predict(X)
        for it, l in zip(its, lab):
            labels[it["ref"]] = offset + int(l)
        offset += int(lab.max()) + 1
    return labels


def score_labels(items: list[dict], gmap: dict[str, str], pred: dict[str, int]) -> dict:
    tp = fp = fn = 0
    b3 = []
    n_pred = n_gold = 0
    by_module = defaultdict(list)
    for it in items:
        by_module[(it["subject"], it["module"])].append(it)
    for _, its in by_module.items():
        gold = [gmap[it["ref"]] for it in its]
        p = [pred[it["ref"]] for it in its]
        a, b, c = pair_counts(gold, p)
        tp, fp, fn = tp + a, fp + b, fn + c
        bc = bcubed(gold, p)
        b3.append((len(its), bc))
        n_pred += len(set(p))
        n_gold += len(set(gold))
    n = sum(w for w, _ in b3)
    return {
        "pairwise": prf(tp, fp, fn),
        "bcubed_f1": sum(w * bc["f1"] for w, bc in b3) / n if n else 0.0,
        "clusters": n_pred, "gold_groups": n_gold,
    }


THRESHOLDS = [round(0.40 + 0.025 * i, 3) for i in range(23)]   # 0.40 … 0.95


def grouping_eval(gt: dict[str, dict], groups: dict[str, dict], models: list[str] | None = None) -> dict:
    gmap = group_map(groups)
    dups = duplicate_scans(gt, gmap)          # a second scan of the same exam would inflate the scores
    gt = {pid: p for pid, p in gt.items() if pid not in dups}
    items = [it for it in gt_items(gt) if it["ref"] in gmap]
    missing = [it["ref"] for it in gt_items(gt) if it["ref"] not in gmap]
    subjects = sorted({it["subject"] for it in items})
    models = models or list(embedders.MODELS)
    configs = []
    for m in models:
        for variant in ("raw", "focus"):
            configs.append((m, "greedy", variant))
            configs.append((m, "average", variant))
    configs.append((embedders.PRODUCTION, "complete", "raw"))

    runs = []
    for model, algo, variant in configs:
        enc = embedders.get(model)
        sweep = []
        for t in THRESHOLDS:
            per_subject = {}
            for s in subjects:
                sub_items = [it for it in items if it["subject"] == s]
                if algo == "greedy":
                    pred = cluster_greedy(sub_items, enc, t, variant)
                else:
                    pred = cluster_agglomerative(sub_items, enc, t, variant, algo)
                per_subject[s] = score_labels(sub_items, gmap, pred)
            tot = Counter()
            for r in per_subject.values():
                tot.update({k: r["pairwise"][k] for k in ("tp", "fp", "fn")})
            sweep.append({"threshold": t, "pairwise": prf(tot["tp"], tot["fp"], tot["fn"]),
                          "bcubed_f1": statistics.mean(r["bcubed_f1"] for r in per_subject.values()),
                          "clusters": sum(r["clusters"] for r in per_subject.values()),
                          "per_subject": per_subject})
        best = max(sweep, key=lambda r: r["pairwise"]["f1"])
        # Leave-one-subject-out: pick τ on the other subjects, score on the held-out one
        loso = {}
        for s in subjects:
            def f1_without(row):
                tot = Counter()
                for k, r in row["per_subject"].items():
                    if k != s:
                        tot.update({x: r["pairwise"][x] for x in ("tp", "fp", "fn")})
                return prf(tot["tp"], tot["fp"], tot["fn"])["f1"]
            chosen = max(sweep, key=f1_without)
            loso[s] = {"threshold": chosen["threshold"], **chosen["per_subject"][s]["pairwise"]}
        lt = Counter()
        for r in loso.values():
            lt.update({k: r[k] for k in ("tp", "fp", "fn")})
        runs.append({
            "model": model, "algorithm": algo, "variant": variant,
            "size_mb": round(enc.size_mb, 1), "embed_seconds": round(enc.seconds, 2),
            "best_threshold": best["threshold"], "best": best["pairwise"], "best_bcubed_f1": best["bcubed_f1"],
            "at_production_threshold": next(r for r in sweep if abs(r["threshold"] - 0.70) < 1e-9)["pairwise"],
            "loso": {"per_subject": loso, **prf(lt["tp"], lt["fp"], lt["fn"])},
            "sweep": [{k: v for k, v in r.items() if k != "per_subject"} for r in sweep],
        })
        print(f"  {model:<26} {algo:<8} {variant:<5}  best F1 {best['pairwise']['f1']:.3f} @ {best['threshold']:.3f}"
              f"   LOSO F1 {runs[-1]['loso']['f1']:.3f}")
    return {"items": len(items), "gold_groups": len({gmap[it["ref"]] for it in items}), "unlabelled": missing,
            "duplicates_dropped": dups, "subjects": subjects, "runs": runs}


# ── 3. Backtest: does the ranking predict the next exam? ──────────────────────

def _question_marks(paper: dict) -> dict[tuple, float]:
    """(q_no, sub_q) → marks, filling missing marks so each question totals 20."""
    by_q = defaultdict(list)
    for q in paper["questions"]:
        by_q[q["q_no"]].append(q)
    out = {}
    for q_no, subs in by_q.items():
        known = sum(s["marks"] for s in subs if s.get("marks"))
        unknown = [s for s in subs if not s.get("marks")]
        fill = max(MODULE_MARKS - known, 0) / len(unknown) if unknown else 0
        for s in subs:
            out[(q_no, s["sub_q"])] = s["marks"] if s.get("marks") else fill
    return out


def exam_score(test_paper: dict, test_id: str, studied_groups: set, gmap: dict) -> float:
    """
    Marks a student secures (out of 100) if they can answer every sub-question whose
    group they studied. VTU rules: each module offers two full questions (Q2m-1 or Q2m);
    the student answers the better one.
    """
    marks = _question_marks(test_paper)
    covered = defaultdict(float)
    for q in test_paper["questions"]:
        if gmap.get(qref(test_id, q)) in studied_groups:
            covered[q["q_no"]] += marks[(q["q_no"], q["sub_q"])]
    total = 0.0
    for m in range(1, 6):
        total += min(MODULE_MARKS, max(covered.get(2 * m - 1, 0.0), covered.get(2 * m, 0.0)))
    return total


def _rank(method: str, topics: list[dict], test_year: int, rng=None) -> list[dict]:
    from modules.scorer import score_canonicals
    if method == "random":
        out = topics[:]
        rng.shuffle(out)
        return out
    if method == "ours":
        scored = score_canonicals([dict(t) for t in topics], max(len({a["paper_id"] for t in topics for a in t["appearances"]}), 1),
                                  current_year=test_year)
        return sorted(scored, key=lambda c: (-c["weighted_score"], -c["frequency"], -(c["avg_marks"] or 0), c["group"]))
    if method == "frequency":
        return sorted(topics, key=lambda c: (-len({a["paper_id"] for a in c["appearances"]}), c["group"]))
    if method == "marks":
        return sorted(topics, key=lambda c: (-(c["avg_marks"] or 0), c["group"]))
    if method == "recency":
        return sorted(topics, key=lambda c: (tuple(-x for x in c["latest"]), -(c["avg_marks"] or 0), c["group"]))
    raise ValueError(method)


def backtest(gt: dict[str, dict], groups: dict[str, dict], system: dict[str, dict] | None = None,
             ks: tuple = tuple(range(0, 9))) -> dict:
    gmap = group_map(groups)
    dups = duplicate_scans(gt, gmap)
    papers = {pid: p for pid, p in gt.items() if pid not in dups}
    by_subject = defaultdict(list)
    for pid, p in papers.items():
        by_subject[p["subject_code"]].append(pid)

    methods = ["ours", "frequency", "recency", "marks", "random"]
    cases = []
    for subject, pids in sorted(by_subject.items()):
        pids.sort(key=lambda x: session_order(papers[x]))
        for test_id in pids:
            test = papers[test_id]
            if test.get("paper_type") != "see":
                continue
            train_ids = [x for x in pids if x != test_id and session_order(papers[x]) < session_order(test)]
            if not train_ids:
                continue
            test_year = test["exam_year"]
            # topics = hand-labelled groups seen in training papers, per module
            topics_by_module = defaultdict(dict)
            for tid in train_ids:
                p = papers[tid]
                order = session_order(p)
                for q in p["questions"]:
                    g = gmap.get(qref(tid, q))
                    if not g:
                        continue
                    t = topics_by_module[q["module"]].setdefault(g, {
                        "group": g, "representative_text": q["text"], "appearances": [], "latest": order})
                    t["appearances"].append({"paper_id": tid, "year": p.get("exam_year"), "marks": q.get("marks")})
                    t["latest"] = max(t["latest"], order)
            for t in (t for mod in topics_by_module.values() for t in mod.values()):
                ms = [a["marks"] for a in t["appearances"] if a["marks"]]
                t["avg_marks"] = float(np.mean(ms)) if ms else 0.0

            seen = {g for mod in topics_by_module.values() for g in mod}
            test_groups = [gmap.get(qref(test_id, q)) for q in test["questions"]]
            marks = _question_marks(test)
            repeat_marks = sum(marks[(q["q_no"], q["sub_q"])] for q in test["questions"] if gmap.get(qref(test_id, q)) in seen)
            case = {
                "subject": subject, "test": test_id, "test_session": session_label(test),
                "train": [f"{x} ({session_label(papers[x])})" for x in train_ids],
                "train_see_papers": sum(papers[x].get("paper_type") == "see" for x in train_ids),
                # both OR alternatives are printed, so a paper carries 200 marks of questions
                "repeat_share_of_marks": repeat_marks / sum(marks.values()),
                "repeated_questions": sum(g in seen for g in test_groups), "test_questions": len(test_groups),
                "ceiling_all_seen": exam_score(test, test_id, seen, gmap),
                "topics_seen_per_module": {m: len(v) for m, v in sorted(topics_by_module.items())},
                "curves": {},
            }
            for method in methods:
                curve = []
                for k in ks:
                    if method == "random":
                        rng = random.Random(1234)
                        vals = []
                        for _ in range(300):
                            studied = set()
                            for mod in topics_by_module.values():
                                studied |= {t["group"] for t in _rank("random", list(mod.values()), test_year, rng)[:k]}
                            vals.append(exam_score(test, test_id, studied, gmap))
                        curve.append(statistics.mean(vals))
                    else:
                        studied = set()
                        for mod in topics_by_module.values():
                            studied |= {t["group"] for t in _rank(method, list(mod.values()), test_year)[:k]}
                        curve.append(exam_score(test, test_id, studied, gmap))
                case["curves"][method] = curve
            # history oracle: best possible score with k seen topics per module (upper bound for any ranking)
            oracle = []
            for k in ks:
                studied = set()
                for mod in topics_by_module.values():
                    gain = Counter()
                    for q in test["questions"]:
                        g = gmap.get(qref(test_id, q))
                        if g in mod:
                            gain[g] += marks[(q["q_no"], q["sub_q"])]
                    studied |= {g for g, _ in gain.most_common(k)}
                oracle.append(exam_score(test, test_id, studied, gmap))
            case["curves"]["oracle"] = oracle
            if system:
                case["curves"]["system_end_to_end"] = _system_curve(subject, train_ids, test, test_id, test_year,
                                                                    gt, system, gmap, ks)
            cases.append(case)
    return {"ks": list(ks), "duplicates_dropped": dups, "cases": cases, "summary": _backtest_summary(cases, ks)}


PASS_MARK = 35   # VTU semester-end exam minimum


def _backtest_summary(cases, ks):
    """Per method, averaged over held-out exams: mean marks across k=1..max (area under the
    curve), marks at k=3, and the fewest topics per module that reach a pass."""
    out = {}
    methods = sorted({m for c in cases for m in c["curves"]})
    for m in methods:
        cs = [c for c in cases if m in c["curves"]]
        auc = [statistics.mean(c["curves"][m][1:]) for c in cs]
        at3 = [c["curves"][m][ks.index(3)] for c in cs]
        to_pass = [next((k for k, v in zip(ks, c["curves"][m]) if v >= PASS_MARK), None) for c in cs]
        out[m] = {"mean_marks_k1_to_max": statistics.mean(auc), "marks_at_k3": statistics.mean(at3),
                  "k_to_pass": to_pass,
                  "k_to_pass_mean": statistics.mean([k for k in to_pass if k is not None]) if any(k is not None for k in to_pass) else None,
                  "cases": len(cs)}
    out["repeat_share_of_marks_mean"] = statistics.mean(c["repeat_share_of_marks"] for c in cases)
    out["ceiling_mean"] = statistics.mean(c["ceiling_all_seen"] for c in cases)
    return out


def _system_curve(subject, train_ids, test, test_id, test_year, gt, system, gmap, ks):
    """
    The deployed pipeline end to end: system-extracted questions, production grouping and
    scoring. A studied system topic covers the hand-labelled groups of the questions in it.
    """
    from modules.deduplicator import deduplicate
    from modules.scorer import score_canonicals
    recs = []
    for tid in train_ids:
        if tid not in system:
            continue
        sys_qs = [q for q in system[tid]["sub_questions"] if 1 <= q["module_no"] <= 5]
        gold = gt[tid]["questions"]
        pairs, _, _ = match_questions(gold, sys_qs)
        gold_of = {j: gmap.get(qref(tid, gold[i])) for i, j, _ in pairs}
        for j, q in enumerate(sys_qs):
            recs.append({"id": f"{tid}#{j}", "text": q["text"], "marks": q.get("marks"), "year": gt[tid].get("exam_year"),
                         "paper_id": tid, "q_no": q["q_no"], "sub_q": q["sub_q"], "module": q["module_no"],
                         "gold": gold_of.get(j)})
    by_module = defaultdict(list)
    for r in recs:
        by_module[r["module"]].append(r)
    ranked_by_module = {}
    gold_lookup = {r["id"]: r["gold"] for r in recs}
    for m, rs in by_module.items():
        canon = score_canonicals(deduplicate(rs), len(train_ids), current_year=test_year)
        ranked_by_module[m] = [{g for g in (gold_lookup[a["sub_question_id"]] for a in c["appearances"]) if g}
                               for c in canon]
    curve = []
    for k in ks:
        studied = set()
        for ranked in ranked_by_module.values():
            for gs in ranked[:k]:
                studied |= gs
        curve.append(exam_score(test, test_id, studied, gmap))
    return curve


# ── 4. Performance ─────────────────────────────────────────────────────────────

def perf(system: dict[str, dict]) -> dict:
    import json
    import os
    import subprocess
    from pathlib import Path

    import psutil

    from eval.common import RAW, ROOT, paper_index
    from modules import detector, parser

    proc = psutil.Process(os.getpid())
    out = {"extraction": []}
    for p in paper_index():
        t0 = time.perf_counter()
        kind, rows = detector.detect_and_extract(str(RAW / p["file"]))
        t1 = time.perf_counter()
        qs = parser.parse_rows(rows)
        t2 = time.perf_counter()
        pages = system.get(p["id"], {}).get("page_count") or len(p.get("pages", [])) or 1
        out["extraction"].append({"paper_id": p["id"], "pdf_type": kind, "pages": pages,
                                  "extract_s": t1 - t0, "parse_s": t2 - t1, "questions": len(qs)})

    texts = [q["text"] for s in system.values() for q in s["sub_questions"]]
    texts = (texts * 3)[:300]
    rss0 = proc.memory_info().rss
    enc = embedders.OnnxEncoder(embedders.DEPLOYED)
    rss1 = proc.memory_info().rss
    enc.encode(texts[:8])
    enc._cache.clear()
    t0 = time.perf_counter()
    enc.encode(texts)
    onnx_s = time.perf_counter() - t0
    out["embedding_onnx"] = {"texts": len(texts), "seconds": onnx_s, "ms_per_text": 1000 * onnx_s / len(texts),
                             "model_rss_mb": (rss1 - rss0) / 1e6, "model_file_mb": enc.size_mb,
                             "process_rss_mb": proc.memory_info().rss / 1e6}

    torch_py = Path(os.environ.get("TORCH_PYTHON", r"C:\Users\Prabhat\miniconda3\python.exe"))
    if torch_py.exists():
        script = ROOT / "eval" / "bench_torch.py"
        tmp = ROOT / "data" / "eval" / "bench_texts.json"
        tmp.write_text(json.dumps(texts), encoding="utf-8")
        r = subprocess.run([str(torch_py), str(script), str(tmp), embedders.MODELS[embedders.DEPLOYED][0]],
                           capture_output=True, text=True, timeout=900)
        try:
            out["embedding_torch"] = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            out["embedding_torch"] = {"error": (r.stderr or r.stdout)[-400:]}
    return out


# ── 2b. Hybrid semantic + key-term similarity ─────────────────────────────────

_STOP = set("""a an the and or of in on at to for with by from is are was be as its it that this these those which what
how why when where who whom explain define describe discuss derive prove show compare differentiate distinguish list
write draw illustrate state evaluate analyse analyze outline find solve give mention enumerate elaborate sketch construct
design develop obtain calculate compute determine identify demonstrate justify apply implement summarise summarize briefly
brief detail details neat suitable relevant clear diagram diagrams figure example examples using use used between various
different following followings each their its also any two three four five term terms meant role importance working work
works concept concepts basic note notes short type types method methods""".split())
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[/\-][A-Za-z0-9]+)*")


def key_terms(text: str) -> tuple[set, set]:
    """(content terms, acronyms) — acronyms keep their exact spelling (CSMA/CA ≠ CSMA/CD)."""
    terms, acr = set(), set()
    for tok in _TOKEN.findall(text):
        low = tok.lower()
        if sum(c.isupper() for c in tok) >= 2 and len(tok) <= 12:
            acr.add(tok.upper())
            terms.add(low)
        elif low not in _STOP and len(low) >= 4:
            terms.add(low[:-1] if low.endswith("s") and len(low) > 4 else low)   # crude plural folding
    return terms, acr


def hybrid_similarity(texts: list[str], X: np.ndarray, alpha: float) -> np.ndarray:
    """(1-α)·cosine + α·(IDF-weighted key-term overlap), minus a penalty when both
    questions name acronyms and none match (CSMA/CA vs CSMA/CD)."""
    n = len(texts)
    kt = [key_terms(t) for t in texts]
    df = Counter(t for terms, _ in kt for t in terms)
    idf = {t: np.log((n + 1) / (c + 0.5)) for t, c in df.items()}
    lex = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = kt[i][0], kt[j][0]
            union = sum(idf[t] for t in a | b)
            v = sum(idf[t] for t in a & b) / union if union else 0.0
            if kt[i][1] and kt[j][1] and not (kt[i][1] & kt[j][1]):
                v -= 0.5
            lex[i, j] = lex[j, i] = v
    np.fill_diagonal(lex, 1.0)
    return (1 - alpha) * (X @ X.T) + alpha * lex


def cluster_hybrid(items, enc, threshold, alpha, linkage="average") -> dict[str, int]:
    from sklearn.cluster import AgglomerativeClustering
    labels, offset = {}, 0
    by_module = defaultdict(list)
    for it in items:
        by_module[(it["subject"], it["module"])].append(it)
    for _, its in sorted(by_module.items()):
        if len(its) == 1:
            labels[its[0]["ref"]] = offset
            offset += 1
            continue
        texts = [it["text"] for it in its]
        S = hybrid_similarity(texts, enc.encode(texts), alpha)
        D = np.clip(1 - S, 0, None)
        lab = AgglomerativeClustering(n_clusters=None, metric="precomputed", linkage=linkage,
                                      distance_threshold=1 - threshold).fit_predict(D)
        for it, l in zip(its, lab):
            labels[it["ref"]] = offset + int(l)
        offset += int(lab.max()) + 1
    return labels


ALPHAS = [0.0, 0.15, 0.3, 0.45]


def hybrid_eval(gt: dict[str, dict], groups: dict[str, dict], models: list[str]) -> dict:
    """Joint (α, τ) grid; leave-one-subject-out picks both on the other subjects."""
    gmap = group_map(groups)
    dups = duplicate_scans(gt, gmap)
    gt = {pid: p for pid, p in gt.items() if pid not in dups}
    items = [it for it in gt_items(gt) if it["ref"] in gmap]
    subjects = sorted({it["subject"] for it in items})
    out = []
    for model in models:
        enc = embedders.get(model)
        grid = []
        for a in ALPHAS:
            for t in THRESHOLDS:
                per_subject = {s: score_labels([i for i in items if i["subject"] == s], gmap,
                                               cluster_hybrid([i for i in items if i["subject"] == s], enc, t, a))
                               for s in subjects}
                tot = Counter()
                for r in per_subject.values():
                    tot.update({k: r["pairwise"][k] for k in ("tp", "fp", "fn")})
                grid.append({"alpha": a, "threshold": t, "pairwise": prf(tot["tp"], tot["fp"], tot["fn"]),
                             "per_subject": per_subject})
        best = max(grid, key=lambda r: r["pairwise"]["f1"])
        loso, lt = {}, Counter()
        for s in subjects:
            def f1_without(row):
                tot = Counter()
                for k, r in row["per_subject"].items():
                    if k != s:
                        tot.update({x: r["pairwise"][x] for x in ("tp", "fp", "fn")})
                return prf(tot["tp"], tot["fp"], tot["fn"])["f1"]
            chosen = max(grid, key=f1_without)
            loso[s] = {"alpha": chosen["alpha"], "threshold": chosen["threshold"], **chosen["per_subject"][s]["pairwise"]}
            lt.update({k: loso[s][k] for k in ("tp", "fp", "fn")})
        out.append({"model": model, "algorithm": "average", "variant": "hybrid", "size_mb": round(enc.size_mb, 1),
                    "best_alpha": best["alpha"], "best_threshold": best["threshold"], "best": best["pairwise"],
                    "loso": {"per_subject": loso, **prf(lt["tp"], lt["fp"], lt["fn"])},
                    "alpha0_best_f1": max(r["pairwise"]["f1"] for r in grid if r["alpha"] == 0.0)})
        print(f"  {model:<26} hybrid  best F1 {best['pairwise']['f1']:.3f} @ α={best['alpha']} τ={best['threshold']}"
              f"   LOSO F1 {out[-1]['loso']['f1']:.3f}   (α=0 best {out[-1]['alpha0_best_f1']:.3f})")
    return {"runs": out}
