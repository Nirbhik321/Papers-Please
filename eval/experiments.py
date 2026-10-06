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
from eval.common import HELD_OUT_PAPERS, load_gt_groups, load_gt_papers, load_system, qref, session_label, session_order
from eval.metrics import bcubed, match_questions, pair_counts, prf
from modules.deduplicator import SIMILARITY_THRESHOLD

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
            by_session[(p["subject_code"], p["exam_year"], p.get("exam_month"), bool(p.get("makeup")))].append(pid)
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

def extraction_eval(gt: dict[str, dict], system: dict[str, dict], min_sim: float = 0.5) -> dict:
    per_paper, totals = [], defaultdict(Counter)
    for pid, paper in gt.items():
        if pid not in system:
            continue
        sys_qs = [q for q in system[pid]["sub_questions"] if 1 <= q["module_no"] <= 5]
        gold = paper["questions"]
        pairs, miss_g, extra_s = match_questions(gold, sys_qs, min_sim=min_sim)
        module_ok = sum(gold[i]["module"] == sys_qs[j]["module_no"] for i, j, _ in pairs)
        label_ok = sum(gold[i]["q_no"] == sys_qs[j]["q_no"] and gold[i]["sub_q"] == sys_qs[j]["sub_q"] for i, j, _ in pairs)
        marks_gold = [(i, j) for i, j, _ in pairs if gold[i].get("marks")]
        marks_ok = sum(gold[i]["marks"] == sys_qs[j].get("marks") for i, j in marks_gold)
        marks_missing = sum(not sys_qs[j].get("marks") for i, j in marks_gold)
        fully_ok = sum(gold[i]["module"] == sys_qs[j]["module_no"] and gold[i]["q_no"] == sys_qs[j]["q_no"]
                       and gold[i]["sub_q"] == sys_qs[j]["sub_q"]
                       and (not gold[i].get("marks") or gold[i]["marks"] == sys_qs[j].get("marks")) for i, j, _ in pairs)
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
        split = "heldout" if pid in HELD_OUT_PAPERS else "dev"
        row["split"] = split
        for key in (kind, "all", split):
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
            t["marks_missing"] += marks_missing
            t["fully_ok"] += fully_ok
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
            # Where each gold sub-question ended up (for the error-breakdown figure)
            "outcomes": {"fully_correct": t["fully_ok"], "matched_with_errors": t["tp"] - t["fully_ok"],
                         "missed": t["fn"], "spurious": t["fp"],
                         "wrong_module": t["tp"] - t["module_ok"], "wrong_label": t["tp"] - t["label_ok"],
                         "marks_missing": t["marks_missing"], "marks_wrong": t["marks_n"] - t["marks_ok"] - t["marks_missing"]},
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


def cluster_production(items: list[dict], enc, threshold: float, variant: str, method: str = "average") -> dict[str, int]:
    """The production code path (deduplicator.deduplicate, including its text cleaning), module
    by module, with the given encoder: method "average" (deployed) or "greedy" (original)."""
    from modules.deduplicator import deduplicate
    labels, next_id = {}, 0
    by_module = defaultdict(list)
    for it in items:
        by_module[(it["subject"], it["module"])].append(it)
    for (_, _), its in sorted(by_module.items()):
        recs = [{"id": it["ref"], "text": it["text"] if variant == "raw" else focus_text(it["text"]),
                 "marks": it["marks"], "year": it["year"], "paper_id": it["paper_id"],
                 "q_no": it["q_no"], "sub_q": it["sub_q"]} for it in its]
        for canon in deduplicate(recs, threshold=threshold, encode=enc.encode, method=method):
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
    modules = {}
    by_module = defaultdict(list)
    for it in items:
        by_module[(it["subject"], it["module"])].append(it)
    for (subject, module), its in by_module.items():
        gold = [gmap[it["ref"]] for it in its]
        p = [pred[it["ref"]] for it in its]
        a, b, c = pair_counts(gold, p)
        tp, fp, fn = tp + a, fp + b, fn + c
        modules[f"{subject}/M{module}"] = (a, b, c)   # pair counts per module, for the bootstrap
        bc = bcubed(gold, p)
        b3.append((len(its), bc))
        n_pred += len(set(p))
        n_gold += len(set(gold))
    n = sum(w for w, _ in b3)
    return {
        "pairwise": prf(tp, fp, fn),
        "bcubed_f1": sum(w * bc["f1"] for w, bc in b3) / n if n else 0.0,
        "clusters": n_pred, "gold_groups": n_gold, "modules": modules,
    }


def _f1_from(counts: list[tuple]) -> float:
    tp, fp, fn = (sum(c[i] for c in counts) for i in range(3))
    return prf(tp, fp, fn)["f1"]


def paired_bootstrap(a: dict[str, tuple], b: dict[str, tuple], n: int = 5000, seed: int = 7) -> dict:
    """
    95% CI for F1(a) - F1(b), resampling modules with replacement (questions are only ever
    grouped within a module, so the module is the independent unit). a, b: module -> (tp, fp, fn).
    """
    keys = sorted(set(a) & set(b))
    rng = random.Random(seed)
    diffs = []
    for _ in range(n):
        sample = [keys[rng.randrange(len(keys))] for _ in keys]
        diffs.append(_f1_from([a[k] for k in sample]) - _f1_from([b[k] for k in sample]))
    diffs.sort()
    return {"diff": _f1_from([a[k] for k in keys]) - _f1_from([b[k] for k in keys]),
            "lo": diffs[int(0.025 * n)], "hi": diffs[int(0.975 * n) - 1],
            "p_le_0": sum(d <= 0 for d in diffs) / n, "units": len(keys)}


# 0.40 … 0.95 in steps of 0.025, plus half steps from 0.85 up: some models (gte, e5, arctic)
# squeeze all their cosine scores into that band, so a coarse grid would handicap them
THRESHOLDS = sorted({round(0.40 + 0.025 * i, 4) for i in range(23)} | {round(0.85 + 0.0125 * i, 4) for i in range(10)})


def _sweep_config(items, gmap, subjects, enc, algo, variant):
    """F1 at every threshold of the encoder's grid, per subject (with per-module pair counts)."""
    sweep = []
    for t in getattr(enc, "thresholds", THRESHOLDS):
        per_subject = {}
        for s in subjects:
            sub_items = [it for it in items if it["subject"] == s]
            if algo in ("greedy", "average"):
                pred = cluster_production(sub_items, enc, t, variant, algo)
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
    return sweep


def _summarise_run(model, algo, variant, enc, sweep, subjects):
    best = max(sweep, key=lambda r: r["pairwise"]["f1"])
    # Leave-one-subject-out: pick τ on the other subjects, score on the held-out one
    loso, loso_modules = {}, {}
    for s in subjects:
        def f1_without(row):
            tot = Counter()
            for k, r in row["per_subject"].items():
                if k != s:
                    tot.update({x: r["pairwise"][x] for x in ("tp", "fp", "fn")})
            return prf(tot["tp"], tot["fp"], tot["fn"])["f1"]
        chosen = max(sweep, key=f1_without)
        loso[s] = {"threshold": chosen["threshold"], **chosen["per_subject"][s]["pairwise"]}
        loso_modules.update(chosen["per_subject"][s]["modules"])
    lt = Counter()
    for r in loso.values():
        lt.update({k: r[k] for k in ("tp", "fp", "fn")})
    # Fixed thresholds: 0.70 (original deployment), 0.725 (the pick made on the first three
    # subjects) and the current deployment, per subject, so a subject added after a choice
    # was made gives a genuinely held-out score for that choice
    fixed = {}
    for t in sorted({0.70, 0.725, SIMILARITY_THRESHOLD}):
        row = next((r for r in sweep if abs(r["threshold"] - t) < 1e-9), None)
        if row:
            fixed[f"{t:.3f}"] = {"per_subject": {s: row["per_subject"][s]["pairwise"] for s in subjects},
                                 "modules": {k: v for s in subjects for k, v in row["per_subject"][s]["modules"].items()}}
    at_070 = next((r for r in sweep if abs(r["threshold"] - 0.70) < 1e-9), None)
    return {
        "model": model, "algorithm": algo, "variant": variant, "family": embedders.family(model),
        "size_mb": round(enc.size_mb, 1), "embed_seconds": round(enc.seconds, 2),
        "best_threshold": best["threshold"], "best": best["pairwise"], "best_bcubed_f1": best["bcubed_f1"],
        "at_production_threshold": at_070["pairwise"] if at_070 else None,
        "loso": {"per_subject": loso, "modules": loso_modules, "ci": bootstrap_f1(loso_modules),
                 **prf(lt["tp"], lt["fp"], lt["fn"])},
        "fixed": fixed,
        "sweep": [{k: v for k, v in r.items() if k != "per_subject"} for r in sweep],
    }


def _model_runs(task):
    """All configurations of one model (runs in its own process)."""
    model, configs, items, gmap, subjects, corpus = task
    embedders.LEXICAL_CORPUS[:] = corpus
    enc = embedders.get(model)
    out = []
    for algo, variant in configs:
        sweep = _sweep_config(items, gmap, subjects, enc, algo, variant)
        run = _summarise_run(model, algo, variant, enc, sweep, subjects)
        print(f"  {model:<26} {algo:<8} {variant:<5}  best F1 {run['best']['f1']:.3f} @ {run['best_threshold']:.3f}"
              f"   LOSO F1 {run['loso']['f1']:.3f}", flush=True)
        out.append((run, sweep))
    return model, out


def bootstrap_f1(modules: dict[str, tuple], n: int = 2000, seed: int = 3) -> tuple[float, float]:
    """95% CI of pooled pairwise F1, resampling modules."""
    keys = sorted(modules)
    if not keys:
        return 0.0, 0.0
    rng = random.Random(seed)
    vals = sorted(_f1_from([modules[keys[rng.randrange(len(keys))]] for _ in keys]) for _ in range(n))
    return vals[int(0.025 * n)], vals[int(0.975 * n) - 1]


def grouping_eval(gt: dict[str, dict], groups: dict[str, dict], models: list[str] | None = None,
                  workers: int = 5) -> dict:
    from concurrent.futures import ProcessPoolExecutor

    gmap = group_map(groups)
    dups = duplicate_scans(gt, gmap)          # a second scan of the same exam would inflate the scores
    gt = {pid: p for pid, p in gt.items() if pid not in dups}
    items = [it for it in gt_items(gt) if it["ref"] in gmap]
    missing = [it["ref"] for it in gt_items(gt) if it["ref"] not in gmap]
    subjects = sorted({it["subject"] for it in items})
    models = models or list(embedders.MODELS)
    corpus = [it["text"] for it in items]     # lexical baselines learn IDF weights from the question texts (no labels)
    tasks = []
    for m in models:
        configs = [(algo, variant) for variant in ("raw", "focus") for algo in ("greedy", "average")]
        if m == embedders.PRODUCTION:
            configs.append(("complete", "raw"))
        tasks.append((m, configs, items, gmap, subjects, corpus))
    # Spread the large models out so no two load at once
    tasks.sort(key=lambda t: embedders.MODEL_ORDER.index(t[0]) if t[0] in embedders.MODEL_ORDER else 0)

    runs, sweeps = [], {}
    with ProcessPoolExecutor(max_workers=workers, max_tasks_per_child=1) as pool:
        for model, out in pool.map(_model_runs, tasks):
            for run, sweep in out:
                runs.append(run)
                sweeps[(run["model"], run["algorithm"], run["variant"])] = sweep

    def run_of(model, algo, variant="raw"):
        return next((r for r in runs if r["model"] == model and r["algorithm"] == algo and r["variant"] == variant), None)

    new, old = run_of(embedders.DEPLOYED, "average"), run_of(embedders.PRODUCTION, "greedy")
    prev = run_of(embedders.PREVIOUS_PICK, "average")
    deployed_t = f"{SIMILARITY_THRESHOLD:.3f}"
    significance = {}
    if new and old:
        significance = {
            "new_loso_vs_old_at_070": paired_bootstrap(new["loso"]["modules"], old["fixed"]["0.700"]["modules"]),
            "new_loso_vs_old_loso": paired_bootstrap(new["loso"]["modules"], old["loso"]["modules"]),
            "new_at_deployed_vs_old_at_070": paired_bootstrap(new["fixed"][deployed_t]["modules"], old["fixed"]["0.700"]["modules"]),
        }
        if prev:
            significance["new_loso_vs_prev_loso"] = paired_bootstrap(new["loso"]["modules"], prev["loso"]["modules"])
            significance["prev_at_0725_vs_old_at_070"] = paired_bootstrap(prev["fixed"]["0.725"]["modules"], old["fixed"]["0.700"]["modules"])
        for k, v in significance.items():
            print(f"  bootstrap {k}: ΔF1 {v['diff']:+.3f}  95% CI [{v['lo']:+.3f}, {v['hi']:+.3f}]  ({v['units']} modules)")
    return {"items": len(items), "gold_groups": len({gmap[it["ref"]] for it in items}), "unlabelled": missing,
            "duplicates_dropped": dups, "subjects": subjects, "runs": runs, "significance": significance,
            "nested": {"deployable": _nested_selection(sweeps, runs, subjects, max_mb=150),
                       "any_size": _nested_selection(sweeps, runs, subjects, max_mb=None)},
            "borderline_merged": _grouping_borderline(items, groups, [(new, SIMILARITY_THRESHOLD), (old, 0.70)])}


def _nested_selection(sweeps: dict, runs: list[dict], subjects: list[str], max_mb: float | None) -> dict:
    """
    Honest estimate of the whole selection procedure: for each subject, pick the model,
    linkage, text variant AND threshold on the other subjects only, then score the subject.
    (Plain LOSO only picks the threshold, after the model was chosen on every subject.)
    """
    size = {(r["model"], r["algorithm"], r["variant"]): r["size_mb"] for r in runs}
    allowed = [k for k in sweeps if max_mb is None or size[k] <= max_mb]
    folds, tot, modules = {}, Counter(), {}
    for s in subjects:
        def f1_without(row):
            t = Counter()
            for k, r in row["per_subject"].items():
                if k != s:
                    t.update({x: r["pairwise"][x] for x in ("tp", "fp", "fn")})
            return prf(t["tp"], t["fp"], t["fn"])["f1"]
        key, row = max(((k, row) for k in allowed for row in sweeps[k]), key=lambda kr: f1_without(kr[1]))
        r = row["per_subject"][s]
        folds[s] = {"model": key[0], "algorithm": key[1], "variant": key[2], "threshold": row["threshold"], **r["pairwise"]}
        tot.update({x: r["pairwise"][x] for x in ("tp", "fp", "fn")})
        modules.update(r["modules"])
    return {"folds": folds, "modules": modules, **prf(tot["tp"], tot["fp"], tot["fn"])}


def _grouping_borderline(items: list[dict], groups: dict, configs: list[tuple]) -> dict:
    """Pairwise F1 of fixed configurations scored against gold groups with every recorded
    borderline pair merged: how much do the annotator's judgement calls move the scores?"""
    merged = group_map(merge_borderline(groups))
    out = {}
    for run, t in configs:
        if not run:
            continue
        enc = embedders.get(run["model"])
        tot = Counter()
        for s in sorted({it["subject"] for it in items}):
            sub_items = [it for it in items if it["subject"] == s]
            pred = cluster_production(sub_items, enc, t, run["variant"], run["algorithm"])
            tot.update({k: score_labels(sub_items, merged, pred)["pairwise"][k] for k in ("tp", "fp", "fn")})
        out[f"{run['model']}|{run['algorithm']}|{t:.3f}"] = prf(tot["tp"], tot["fp"], tot["fn"])
    return out


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


SEEDS = 200   # random tie-breaks per ranking (and orders for the random baseline)


def _sort_keys(method: str, topics: list[dict], test_year: int) -> dict[str, tuple]:
    """Group -> sort key (smaller ranks first). Ties are broken at random by the caller,
    so no ranking can benefit from the order in which groups happened to be annotated."""
    from modules.scorer import score_canonicals
    if method == "random":
        return {t["group"]: () for t in topics}
    if method == "ours":   # exactly what production does: scorer.score_canonicals and its tie-breaks
        scored = score_canonicals([dict(t) for t in topics], max(len({a["paper_id"] for t in topics for a in t["appearances"]}), 1),
                                  current_year=test_year)
        return {c["group"]: (-c["weighted_score"], -c["frequency"], -(c["avg_marks"] or 0)) for c in scored}
    if method == "frequency":
        return {t["group"]: (-len({a["paper_id"] for a in t["appearances"]}),) for t in topics}
    if method == "marks":
        return {t["group"]: (-(t["avg_marks"] or 0),) for t in topics}
    if method == "recency":
        return {t["group"]: tuple(-x for x in t["latest"]) for t in topics}
    raise ValueError(method)


def _tied_share(topics_by_module: dict, test_year: int, k: int = 3) -> float:
    """Share of modules where our ranking's top-k cut falls inside a tie (so chance decides)."""
    tied = n = 0
    for mod in topics_by_module.values():
        keys = sorted(_sort_keys("ours", list(mod.values()), test_year).values())
        if len(keys) > k:
            n += 1
            tied += keys[k - 1] == keys[k]
    return tied / n if n else 0.0


def _curve(method: str, topics_by_module: dict, test: dict, test_id: str, test_year: int, gmap: dict, ks) -> list[float]:
    """Mean exam score at each k over SEEDS random tie-breaks."""
    keyed = {m: (list(mod), _sort_keys(method, list(mod.values()), test_year)) for m, mod in topics_by_module.items()}
    sums = [0.0] * len(ks)
    for seed in range(SEEDS):
        rng = random.Random(seed)
        orders = {}
        for m, (groups, keys) in keyed.items():
            order = groups[:]
            rng.shuffle(order)
            order.sort(key=lambda g: keys[g])     # stable: equal keys stay in the shuffled order
            orders[m] = order
        for i, k in enumerate(ks):
            studied = {g for order in orders.values() for g in order[:k]}
            sums[i] += exam_score(test, test_id, studied, gmap)
    return [s / SEEDS for s in sums]


def _oracle_curve(topics_by_module: dict, test: dict, test_id: str, gmap: dict, ks) -> list[float]:
    """
    Upper bound for any ranking of seen topics: per module, the better of the two alternative
    questions, each covered by its own k most valuable seen topics (a student answers one
    question per module, so covering one fully beats spreading topics over both).
    """
    marks = _question_marks(test)
    gains = defaultdict(Counter)            # q_no -> group -> marks in that question
    for q in test["questions"]:
        g = gmap.get(qref(test_id, q))
        if g in topics_by_module.get(q["module"], {}):
            gains[q["q_no"]][g] += marks[(q["q_no"], q["sub_q"])]
    out = []
    for k in ks:
        total = 0.0
        for m in range(1, 6):
            best = 0.0
            for q_no in (2 * m - 1, 2 * m):
                best = max(best, min(MODULE_MARKS, sum(v for _, v in gains[q_no].most_common(k))))
            total += best
        out.append(total)
    return out


def backtest(gt: dict[str, dict], groups: dict[str, dict], system: dict[str, dict] | None = None,
             ks: tuple = tuple(range(0, 9)), exams_only: bool = False, extras: bool = True) -> dict:
    """exams_only=True trains on earlier real exams only, leaving out the official model papers.
    extras=False skips the reappearance, exams-only and borderline-merged variants."""
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
            train_ids = [x for x in pids if x != test_id and session_order(papers[x]) < session_order(test)
                         and (not exams_only or papers[x].get("paper_type") == "see")]
            if not train_ids:
                continue
            unlabelled = [qref(test_id, q) for q in test["questions"] if qref(test_id, q) not in gmap]
            if unlabelled:
                raise ValueError(f"{test_id}: {len(unlabelled)} test questions have no gold group, e.g. {unlabelled[0]}")
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
            case["tied_share_at_k3"] = _tied_share(topics_by_module, test_year)
            for method in methods:
                case["curves"][method] = _curve(method, topics_by_module, test, test_id, test_year, gmap, ks)
            case["curves"]["oracle"] = _oracle_curve(topics_by_module, test, test_id, gmap, ks)
            if system:
                case["curves"]["system_end_to_end"] = _system_curve(subject, train_ids, test, test_id, test_year,
                                                                    gt, system, gmap, ks)
            cases.append(case)
    out = {"ks": list(ks), "duplicates_dropped": dups, "cases": cases, "summary": _backtest_summary(cases, ks)}
    if extras:
        out["reappearance"] = reappearance(gt, groups)
        # How much do the official model papers contribute? Same backtest, earlier real exams only
        eo = backtest(gt, groups, None, ks, exams_only=True, extras=False)
        out["exams_only"] = {"summary": eo["summary"],
                             "cases": [{k: c[k] for k in ("subject", "test_session", "train", "ceiling_all_seen")} for c in eo["cases"]]}
        # Robustness to the annotator's borderline calls: merge every recorded borderline pair
        out["borderline_merged"] = {"summary": backtest(gt, merge_borderline(groups), None, ks, extras=False)["summary"]}
    return out


def merge_borderline(groups: dict[str, dict]) -> dict[str, dict]:
    """The gold groups with every recorded borderline pair merged (union-find), for robustness checks."""
    out = {}
    for subject, g in groups.items():
        parent = list(range(len(g["groups"])))
        where = {m: i for i, grp in enumerate(g["groups"]) for m in grp["members"]}

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        for b in g.get("borderline", []):
            ids = [where[m] for m in b["members"] if m in where]
            for a, c in zip(ids, ids[1:]):
                parent[find(a)] = find(c)
        merged = defaultdict(list)
        for i, grp in enumerate(g["groups"]):
            merged[find(i)].extend(grp["members"])
        out[subject] = {**g, "groups": [{"label": f"merged {k}", "members": v} for k, v in merged.items()]}
    return out


def _sign_test(wins: int, losses: int) -> float:
    """Exact two-sided sign test p-value (ties dropped)."""
    from math import comb
    n = wins + losses
    if not n:
        return 1.0
    tail = sum(comb(n, i) for i in range(0, min(wins, losses) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if not n:
        return 0.0, 0.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
    return centre - half, centre + half


def reappearance(gt: dict[str, dict], groups: dict[str, dict]) -> dict:
    """
    Base rates behind the ranking: of the topics seen before an exam, how often does each
    kind come back in it? Split by how many earlier papers carried the topic, and by whether
    the most recent earlier exam asked it.
    """
    gmap = group_map(groups)
    dups = duplicate_scans(gt, gmap)
    papers = {pid: p for pid, p in gt.items() if pid not in dups}
    topics_of = {pid: {gmap[qref(pid, q)] for q in p["questions"] if qref(pid, q) in gmap} for pid, p in papers.items()}
    by_subject = defaultdict(list)
    for pid, p in papers.items():
        by_subject[p["subject_code"]].append(pid)
    per_exam = []
    for pids in by_subject.values():
        for test_id in pids:
            test = papers[test_id]
            if test.get("paper_type") != "see":
                continue
            train = [x for x in pids if session_order(papers[x]) < session_order(test)]
            if not train:
                continue
            exams = [x for x in train if papers[x].get("paper_type") == "see"]
            last = topics_of[max(exams, key=lambda x: session_order(papers[x]))] if exams else set()
            seen = Counter(g for x in train for g in topics_of[x])
            counts = defaultdict(lambda: [0, 0])
            for g, n in seen.items():
                back = g in topics_of[test_id]
                for key in ("seen_once" if n == 1 else "seen_2plus", "in_last_exam" if g in last else "not_in_last_exam", "all"):
                    counts[key][0] += back
                    counts[key][1] += 1
            per_exam.append(counts)

    # Topics within one exam are not independent, so the intervals resample whole exams
    def rate(sample, key):
        a = sum(e[key][0] for e in sample if key in e)
        n = sum(e[key][1] for e in sample if key in e)
        return a / n if n else float("nan")
    rng = random.Random(5)
    boots = [[per_exam[rng.randrange(len(per_exam))] for _ in per_exam] for _ in range(5000)]
    out = {}
    for key in ("seen_once", "seen_2plus", "in_last_exam", "not_in_last_exam", "all"):
        vals = sorted(v for v in (rate(s, key) for s in boots) if v == v)
        a = sum(e[key][0] for e in per_exam if key in e)
        n = sum(e[key][1] for e in per_exam if key in e)
        out[key] = {"back": a, "seen": n, "rate": a / n if n else 0.0,
                    "ci": (vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]) if vals else (0.0, 0.0)}
    for a_key, b_key, name in (("seen_2plus", "seen_once", "repeat_vs_once"), ("in_last_exam", "not_in_last_exam", "last_vs_not")):
        diffs = sorted(d for d in (rate(s, a_key) - rate(s, b_key) for s in boots) if d == d)
        out[name] = {"diff": out[a_key]["rate"] - out[b_key]["rate"],
                     "lo": diffs[int(0.025 * len(diffs))], "hi": diffs[int(0.975 * len(diffs)) - 1]}
    out["exams"] = len(per_exam)
    return out


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
                  "reach_pass": sum(k is not None for k in to_pass),
                  "cases": len(cs)}
    out["repeat_share_of_marks_mean"] = statistics.mean(c["repeat_share_of_marks"] for c in cases)
    out["ceiling_mean"] = statistics.mean(c["ceiling_all_seen"] for c in cases)

    # Ours vs random at k=3: per-exam gains, how many exams ours wins, and a bootstrap CI over exams
    k3 = ks.index(3)
    for other in ("random", "frequency"):
        gains = [c["curves"]["ours"][k3] - c["curves"][other][k3] for c in cases]
        rng = random.Random(11)
        boot = sorted(statistics.mean(gains[rng.randrange(len(gains))] for _ in gains) for _ in range(5000))
        wins, losses = sum(g > 0.05 for g in gains), sum(g < -0.05 for g in gains)
        out[f"ours_vs_{other}_k3"] = {"gains": gains, "mean": statistics.mean(gains), "lo": boot[125], "hi": boot[4874],
                                      "wins": wins, "losses": losses, "ties": len(gains) - wins - losses, "cases": len(gains),
                                      "sign_p": _sign_test(wins, losses)}

    # Does more history help? Group exams by how many earlier papers the ranking had
    by_n = defaultdict(list)
    for c in cases:
        by_n[len(c["train"])].append(c)
    out["by_train_papers"] = {
        n: {"cases": len(cs),
            **{m: statistics.mean(c["curves"][m][k3] for c in cs) for m in methods if all(m in c["curves"] for c in cs)},
            "ceiling": statistics.mean(c["ceiling_all_seen"] for c in cs),
            "repeat_share": statistics.mean(c["repeat_share_of_marks"] for c in cs)}
        for n, cs in sorted(by_n.items())}
    return out


def _system_curve(subject, train_ids, test, test_id, test_year, gt, system, gmap, ks):
    """
    The deployed pipeline end to end: system-extracted questions, production grouping and
    scoring. A studied system topic covers the hand-labelled groups of the questions in it.
    """
    from modules.deduplicator import deduplicate
    from modules.scorer import fill_missing_marks, score_canonicals
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
    for r in fill_missing_marks(recs):       # as production does before ranking
        by_module[r["module"]].append(r)
    ranked_by_module = {}
    gold_lookup = {r["id"]: r["gold"] for r in recs}
    for m, rs in by_module.items():
        canon = score_canonicals(deduplicate(rs), len(train_ids), current_year=test_year)
        # Studying a system topic means preparing what most of its questions ask: credit only its
        # majority gold group, so a cluster that wrongly merges several topics earns no extra marks
        ranked = []
        for c in canon:
            gs = Counter(g for g in (gold_lookup[a["sub_question_id"]] for a in c["appearances"]) if g)
            if gs:
                ranked.append(gs.most_common(1)[0][0])
        ranked_by_module[m] = ranked
    curve = []
    for k in ks:
        studied = {g for ranked in ranked_by_module.values() for g in ranked[:k]}
        curve.append(exam_score(test, test_id, studied, gmap))
    return curve


# ── 4. Performance ─────────────────────────────────────────────────────────────

def perf(system: dict[str, dict]) -> dict:
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    from eval.common import RAW, ROOT, paper_index
    from modules import detector, parser

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
    texts = list(dict.fromkeys(texts))[:300]   # distinct texts: the encoder memoises repeats
    tmp = ROOT / "data" / "eval" / "bench_texts.json"
    tmp.write_text(json.dumps(texts), encoding="utf-8")

    def bench(cmd: list[str]) -> dict:
        # A fresh interpreter per runtime, so memory covers only that runtime and model
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900, cwd=ROOT,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        try:
            return json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            return {"error": (r.stderr or r.stdout)[-400:]}

    out["embedding_onnx"] = bench([sys.executable, "-m", "eval.bench_onnx", str(tmp), embedders.DEPLOYED])
    torch_py = Path(os.environ.get("TORCH_PYTHON", r"C:\Users\Prabhat\miniconda3\python.exe"))
    if torch_py.exists():
        out["embedding_torch"] = bench([str(torch_py), str(ROOT / "eval" / "bench_torch.py"), str(tmp),
                                        embedders.MODELS[embedders.DEPLOYED][0]])
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
