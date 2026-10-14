"""
Turn eval/results/results.json into LaTeX the paper \\input{}s, so every number in the
paper comes from the evaluation and updates when papers are added:

  reports/generated/macros.tex        \\newcommand{\\Something}{value}
  reports/generated/tab_dataset.tex   dataset table
  reports/generated/tab_extraction.tex
  reports/generated/tab_models.tex
  reports/generated/tab_backtest.tex
"""

import statistics
from collections import Counter

from eval import embedders
from eval.common import HELD_OUT_SUBJECTS, ROOT, load_gt_groups, load_gt_papers, session_label
from modules.deduplicator import SIMILARITY_THRESHOLD

OUT = ROOT / "reports" / "generated"
class _Display(dict):
    """Short model names for tables: drop version suffixes, keep the rest."""
    _OVERRIDE = {"tfidf-word": "TF-IDF (words)", "tfidf-char": "TF-IDF (char n-grams)",
                 "nomic-embed-text-v1.5": "nomic-embed-v1.5", "multi-qa-MiniLM-L6": "multi-qa-MiniLM-L6"}

    def __missing__(self, key):
        import re
        return self._OVERRIDE.get(key) or re.sub(r"-v\d$", "", key).replace("-en-v1.5", "-en")


DISPLAY = _Display()
METHOD = {"ours": "Ours (freq.\\ $\\times$ recency)", "system_end_to_end": "Ours, end-to-end",
          "frequency": "Frequency only", "recency": "Most recent first", "marks": "Highest marks first",
          "random": "Random order", "oracle": "Hindsight oracle"}


def _f(x, d=3):
    return f"{x:.{d}f}"


def _pct(x, d=1):
    return f"{100 * x:.{d}f}\\%"


def build(res: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    m = {}
    gt, groups = load_gt_papers(), load_gt_groups()

    # ── Dataset ──
    subjects = sorted({p["subject_code"] for p in gt.values()})
    m["NumPapers"] = len(gt)
    m["NumSubjects"] = len(subjects)
    m["NumQuestions"] = sum(len(p["questions"]) for p in gt.values())
    m["NumScanned"] = sum(1 for pid in gt if res.get("extraction") and
                          any(r["paper_id"] == pid and r["pdf_type"] == "scanned" for r in res["extraction"]["per_paper"]))
    m["NumNative"] = m["NumPapers"] - m["NumScanned"]
    m["NumGroups"] = sum(len(g["groups"]) for g in groups.values())
    m["NumBorderline"] = sum(len(g.get("borderline", [])) for g in groups.values())
    rows = []
    kinds = {r["paper_id"]: r["pdf_type"] for r in res.get("extraction", {}).get("per_paper", [])}
    for s in subjects:
        ps = sorted((pid for pid, p in gt.items() if p["subject_code"] == s), key=lambda x: (gt[x].get("paper_type") != "model", gt[x].get("exam_year") or 0))
        name = gt[ps[0]].get("subject_name") or s
        sessions = ", ".join(session_label(gt[pid]) for pid in ps)
        nq = sum(len(gt[pid]["questions"]) for pid in ps)
        scans = sum(kinds.get(pid) == "scanned" for pid in ps)
        ng = len(groups.get(s, {}).get("groups", []))
        multi = sum(1 for g in groups.get(s, {}).get("groups", []) if len(g["members"]) > 1)
        rows.append(f"{s} & {name} & {len(ps)} ({scans}) & {nq} & {ng} ({multi}) \\\\")
    (OUT / "tab_dataset.tex").write_text(
        "\\begin{tabular}{@{}l>{\\raggedright\\arraybackslash}p{3.1cm}ccc@{}}\n\\toprule\n\\textbf{Code} & \\textbf{Subject} & "
        "\\textbf{Papers} & \\textbf{Sub-q.} & \\textbf{Groups} \\\\\n\\midrule\n" + "\n".join(rows) +
        f"\n\\midrule\n\\textbf{{Total}} & & {m['NumPapers']} ({m['NumScanned']}) & {m['NumQuestions']} & {m['NumGroups']} \\\\\n"
        "\\bottomrule\n\\end{tabular}\n", encoding="utf-8")

    # ── Extraction ──
    if "extraction" in res:
        s = res["extraction"]["summary"]
        lines = []
        for key, label in (("native", "Native text"), ("scanned", "Scanned (OCR)"), ("all", "\\textbf{All}"),
                           ("heldout", "Unseen (added later)")):
            if key not in s:
                continue
            r = s[key]
            if key == "heldout":
                lines.append("\\midrule")
            lines.append(f"{label} & {r['papers']} & {r['gold']} & {_f(r['precision'],2)} & {_f(r['recall'],2)} & "
                         f"{_f(r['f1'],2)} & {_f(r['module_acc'],2)} & {_f(r['label_acc'],2)} & {_f(r['marks_acc'],2)} \\\\")
        for key in ("native", "scanned", "all", "heldout", "dev"):
            if key not in s:
                continue
            r = s[key]
            tag = {"native": "Native", "scanned": "Scanned", "all": "All", "heldout": "Heldout", "dev": "Dev"}[key]
            m[f"Ext{tag}Papers"] = r["papers"]
            m[f"Ext{tag}Gold"] = r["gold"]
            for k, v in (("F", r["f1"]), ("P", r["precision"]), ("R", r["recall"]), ("Module", r["module_acc"]),
                         ("Label", r["label_acc"]), ("Marks", r["marks_acc"]), ("Text", r["text_sim"])):
                m[f"Ext{tag}{k}"] = _f(v, 2)
        # Scans only, split by development/unseen (the native/scan mix differs between the splits), and the
        # unseen papers without the second scans of exams already in the development set
        per = res["extraction"]["per_paper"]
        dups = set(res.get("grouping", {}).get("duplicates_dropped", {}))

        def _agg(rows):
            tp, fp, fn = (sum(r[k] for r in rows) for k in ("tp", "fp", "fn"))
            pr, rc = tp / (tp + fp) if tp + fp else 0.0, tp / (tp + fn) if tp + fn else 0.0
            acc = {k: sum(r[k] * r["tp"] for r in rows) / tp if tp else 0.0 for k in ("module_acc", "label_acc", "marks_acc")}
            return {"papers": len(rows), "f1": 2 * pr * rc / (pr + rc) if pr + rc else 0.0, **acc}
        for split, tag in (("dev", "Dev"), ("heldout", "Heldout")):
            rows = [r for r in per if r.get("split") == split]
            m[f"Ext{tag}NativePapers"] = sum(r["pdf_type"] == "native" for r in rows)
            a = _agg([r for r in rows if r["pdf_type"] == "scanned"])
            m[f"Ext{tag}ScanPapers"] = a["papers"]
            m[f"Ext{tag}ScanF"], m[f"Ext{tag}ScanModule"], m[f"Ext{tag}ScanLabel"] = (
                _f(a["f1"], 2), _f(a["module_acc"], 2), _f(a["label_acc"], 2))
        a = _agg([r for r in per if r.get("split") == "heldout" and r["paper_id"] not in dups])
        m["ExtHeldoutNoDupPapers"] = a["papers"]
        m["ExtHeldoutNoDupF"], m["ExtHeldoutNoDupModule"], m["ExtHeldoutNoDupLabel"] = (
            _f(a["f1"], 2), _f(a["module_acc"], 2), _f(a["label_acc"], 2))
        for t, summ in res["extraction"].get("match_sensitivity", {}).items():
            tag = {"0.3": "Low", "0.7": "High"}.get(t)
            for key, name in (("scanned", "Scanned"), ("all", "All"), ("native", "Native")):
                if tag and key in summ:
                    m[f"Ext{name}FAt{tag}"] = _f(summ[key]["f1"], 2)
        (OUT / "tab_extraction.tex").write_text(
            "\\begin{tabular}{@{}lcccccccc@{}}\n\\toprule\n\\textbf{PDFs} & \\textbf{N} & \\textbf{Gold} & \\textbf{P} & "
            "\\textbf{R} & \\textbf{F1} & \\textbf{Mod.} & \\textbf{Label} & \\textbf{Marks} \\\\\n\\midrule\n"
            + "\n".join(lines) + "\n\\bottomrule\n\\end{tabular}\n", encoding="utf-8")

    # ── Grouping ──
    if "grouping" in res:
        g = res["grouping"]
        m["GroupItems"] = g["items"]
        m["GroupGold"] = g["gold_groups"]
        runs = g["runs"]

        def run_of(model, algo, variant="raw"):
            return next((r for r in runs if r["model"] == model and r["algorithm"] == algo and r["variant"] == variant), None)

        best_per_model = {}
        for r in runs:
            if r["algorithm"] == "complete":
                continue
            cur = best_per_model.get(r["model"])
            if cur is None or r["loso"]["f1"] > cur["loso"]["f1"]:
                best_per_model[r["model"]] = r
        lines = []
        ranked_models = sorted(best_per_model.values(), key=lambda r: -r["loso"]["f1"])
        must = {embedders.DEPLOYED, embedders.PREVIOUS_PICK, embedders.PRODUCTION} | set(embedders.LEXICAL)
        shown = [r for i, r in enumerate(ranked_models) if i < 4 or r["model"] in must]   # the figure shows all
        for r in shown:
            lines.append(f"{DISPLAY[r['model']]} & {r['size_mb']:.0f} & {r['algorithm'][:3]}. & {r['variant']} & "
                         f"{r['best_threshold']:.3f} & {_f(r['best']['precision'],2)} & {_f(r['best']['recall'],2)} & "
                         f"{_f(r['best']['f1'])} & {_f(r['loso']['f1'])} \\\\")
        (OUT / "tab_models.tex").write_text(
            "\\begin{tabular}{@{}lrllccccc@{}}\n\\toprule\n\\textbf{Model} & \\textbf{MB} & \\textbf{Link.} & \\textbf{Text} & "
            "$\\boldsymbol{\\tau^*}$ & \\textbf{P} & \\textbf{R} & \\textbf{F1} & \\textbf{LOSO} \\\\\n\\midrule\n" + "\n".join(lines) +
            "\n\\bottomrule\n\\end{tabular}\n", encoding="utf-8")

        old = run_of(embedders.PRODUCTION, "greedy")
        new = run_of(embedders.DEPLOYED, "average")
        prev = run_of(embedders.PREVIOUS_PICK, "average")
        deployed_t = f"{SIMILARITY_THRESHOLD:.3f}"
        m["NewModel"] = DISPLAY[embedders.DEPLOYED]
        m["PrevModel"] = DISPLAY[embedders.PREVIOUS_PICK]
        m["OldModel"] = DISPLAY[embedders.PRODUCTION]
        m["OldFAtSeventy"] = _f(old["at_production_threshold"]["f1"])
        m["OldLoso"] = _f(old["loso"]["f1"])
        m["OldBestTau"] = f"{old['best_threshold']:.3f}"
        m["OldBcubed"] = _f(old["best_bcubed_f1"])
        m["NewLoso"] = _f(new["loso"]["f1"])
        m["NewBestF"] = _f(new["best"]["f1"])
        m["NewTau"] = f"{SIMILARITY_THRESHOLD:.3f}"
        m["NewBestTau"] = f"{new['best_threshold']:.3f}"
        m["NewP"] = _f(new["best"]["precision"], 2)
        m["NewR"] = _f(new["best"]["recall"], 2)
        m["NewBcubed"] = _f(new["best_bcubed_f1"])
        m["NewMB"] = f"{new['size_mb']:.0f}"
        m["NewLosoTaus"] = ", ".join(sorted({f"{v['threshold']:.3f}" for v in new["loso"]["per_subject"].values()}))
        m["LosoGain"] = f"{100 * (new['loso']['f1'] - old['at_production_threshold']['f1']):.1f}"
        m["PrevLoso"] = _f(prev["loso"]["f1"])
        m["PrevMB"] = f"{prev['size_mb']:.0f}"
        greedy_new = run_of(embedders.DEPLOYED, "greedy")
        m["NewGreedyLoso"] = _f(greedy_new["loso"]["f1"])
        focus_drop = [r["loso"]["f1"] - run_of(r["model"], r["algorithm"])["loso"]["f1"] for r in runs if r["variant"] == "focus"]
        m["FocusMeanDrop"] = f"{-100 * statistics.mean(focus_drop):.1f}"
        m["FocusHelps"] = sum(d > 0.005 for d in focus_drop)
        m["FocusRuns"] = len(focus_drop)
        mp = run_of("all-mpnet-base-v2", "average")
        m["MpnetLoso"] = _f(mp["loso"]["f1"])
        m["MpnetMB"] = f"{mp['size_mb']:.0f}"
        avg_wins = sum(1 for r in runs if r["algorithm"] == "average" and r["variant"] == "raw"
                       and r["loso"]["f1"] > run_of(r["model"], "greedy")["loso"]["f1"] + 0.005)
        m["AvgWins"] = avg_wins
        m["NumModels"] = len(best_per_model)
        m["NumConfigs"] = len(runs)
        top = sorted(best_per_model.values(), key=lambda r: -r["loso"]["f1"])
        m["TopThreeSpread"] = _f(top[0]["loso"]["f1"] - top[2]["loso"]["f1"])
        m["NumModules"] = len(new["loso"]["modules"])
        m["HeldoutSubjects"] = ", ".join(sorted(HELD_OUT_SUBJECTS))
        held = [s for s in g["subjects"] if s in HELD_OUT_SUBJECTS]
        if held:
            def fixed_f1(run, t):
                tot = Counter()
                for s in held:
                    tot.update({k: run["fixed"][t]["per_subject"][s][k] for k in ("tp", "fp", "fn")})
                p, r_ = tot["tp"] / max(tot["tp"] + tot["fp"], 1), tot["tp"] / max(tot["tp"] + tot["fn"], 1)
                return 2 * p * r_ / (p + r_) if p + r_ else 0.0
            # The pick made on the first three subjects, scored on the subject added afterwards
            m["HeldoutPrevF"] = _f(fixed_f1(prev, "0.725"))
            m["HeldoutOldF"] = _f(fixed_f1(old, "0.700"))
            m["HeldoutPrevGain"] = f"{100 * (fixed_f1(prev, '0.725') - fixed_f1(old, '0.700')):.1f}"
            m["HeldoutNewLosoF"] = _f(statistics.mean(new["loso"]["per_subject"][s]["f1"] for s in held))
        sig = g.get("significance", {})
        for key, tag in (("new_loso_vs_old_at_070", "Loso"), ("new_loso_vs_old_loso", "LosoTuned"),
                         ("new_at_deployed_vs_old_at_070", "Fixed"), ("new_loso_vs_prev_loso", "VsPrev"),
                         ("prev_at_0725_vs_old_at_070", "Prev")):
            if key in sig:
                m[f"Sig{tag}Lo"] = f"{100 * sig[key]['lo']:.1f}"
                m[f"Sig{tag}Hi"] = f"{100 * sig[key]['hi']:.1f}"
                m[f"Sig{tag}Diff"] = f"{100 * sig[key]['diff']:.1f}"
                m["SigUnits"] = sig[key]["units"]
        for key, tag in (("deployable", "Nested"), ("any_size", "NestedAny")):
            n = g.get("nested", {}).get(key)
            if n:
                m[f"{tag}F"] = _f(n["f1"])
                picks = Counter(DISPLAY[f["model"]] for f in n["folds"].values())
                m[f"{tag}Picks"] = ", ".join(f"{k} ({v})" for k, v in picks.most_common())
        for key, val in g.get("borderline_merged", {}).items():
            model = key.split("|")[0]
            tag = "New" if model == embedders.DEPLOYED else "Old"
            m[f"Border{tag}F"] = _f(val["f1"])
        m["Deployed"] = deployed_t
        m["NewLosoLo"], m["NewLosoHi"] = (_f(x) for x in new["loso"]["ci"])
        neural = [r for r in ranked_models if r["model"] not in embedders.LEXICAL]
        lexical = [r for r in ranked_models if r["model"] in embedders.LEXICAL]
        m["NumNeural"] = len(neural)
        m["NumLexical"] = len(lexical)
        m["BestModel"] = DISPLAY[neural[0]["model"]]
        m["BestModelF"] = _f(neural[0]["loso"]["f1"])
        m["BestModelMB"] = f"{neural[0]['size_mb']:.0f}"
        if lexical:
            m["LexBestModel"] = DISPLAY[lexical[0]["model"]]
            m["LexBestF"] = _f(lexical[0]["loso"]["f1"])
            m["LexBestLo"], m["LexBestHi"] = (_f(x) for x in lexical[0]["loso"]["ci"])
            for r in lexical:
                m["Lex" + ("Word" if r["model"].endswith("word") else "Char") + "F"] = _f(r["loso"]["f1"])
            m["NeuralOverLexical"] = f"{100 * (new['loso']['f1'] - lexical[0]['loso']['f1']):.1f}"
            m["NeuralBeatsLexical"] = sum(r["loso"]["f1"] > lexical[0]["loso"]["f1"] for r in neural)
        large = [r for r in neural if r["size_mb"] > 1000]
        if large:
            m["LargeBestModel"] = DISPLAY[large[0]["model"]]
            m["LargeBestF"] = _f(large[0]["loso"]["f1"])
            m["LargeMB"] = f"{large[0]['size_mb']:.0f}"
        deployable = [r for r in neural if r["size_mb"] <= 150]
        m["NumDeployable"] = len(deployable)
        m["DeployableTopSpread"] = _f(deployable[0]["loso"]["f1"] - deployable[min(2, len(deployable) - 1)]["loso"]["f1"])
        m["NewRank"] = 1 + [r["model"] for r in neural].index(embedders.DEPLOYED)
    if "grouping_hybrid" in res:
        for r in res["grouping_hybrid"]["runs"]:
            tag = "New" if r["model"] == embedders.DEPLOYED else "Old"
            m[f"Hybrid{tag}Loso"] = _f(r["loso"]["f1"])

    # ── Backtest ──
    if "backtest" in res:
        b = res["backtest"]
        s = b["summary"]
        m["BtCases"] = len(b["cases"])
        m["BtRepeatShare"] = _pct(s["repeat_share_of_marks_mean"], 0)
        m["BtCeiling"] = f"{s['ceiling_mean']:.1f}"
        for key, tag in (("ours", "Ours"), ("system_end_to_end", "Sys"), ("frequency", "Freq"), ("recency", "Rec"),
                         ("marks", "Marks"), ("random", "Rand"), ("oracle", "Oracle")):
            if key in s:
                m[f"Bt{tag}Auc"] = f"{s[key]['mean_marks_k1_to_max']:.1f}"
                m[f"Bt{tag}AtThree"] = f"{s[key]['marks_at_k3']:.1f}"
                m[f"Bt{tag}ToPass"] = f"{s[key]['k_to_pass_mean']:.1f}" if s[key]["k_to_pass_mean"] is not None else "--"
        m["BtGainOverRandom"] = f"{s['ours']['marks_at_k3'] - s['random']['marks_at_k3']:.1f}"
        for other, tag in (("random", "Gain"), ("frequency", "VsFreq")):
            v = s.get(f"ours_vs_{other}_k3")
            if v:
                m[f"Bt{tag}Mean"] = f"{v['mean']:.1f}"
                m[f"Bt{tag}Lo"] = f"{v['lo']:.1f}"
                m[f"Bt{tag}Hi"] = f"{v['hi']:.1f}"
                m[f"Bt{tag}Wins"] = v["wins"]
                m[f"Bt{tag}Losses"] = v["losses"]
                m[f"Bt{tag}Ties"] = v["ties"]
                m[f"Bt{tag}SignP"] = f"{v['sign_p']:.3f}"
        if "ours_vs_random_k3" in s:
            m["BtWins"] = s["ours_vs_random_k3"]["wins"]
        m["BtOursReachPass"] = s["ours"].get("reach_pass", "--")
        m["BtTiedShare"] = _pct(statistics.mean(c.get("tied_share_at_k3", 0) for c in b["cases"]), 0)
        m["BtModelPaperShare"] = _pct(statistics.mean(1 - c["train_see_papers"] / len(c["train"]) for c in b["cases"]), 0)
        eo = b.get("exams_only", {}).get("summary")
        if eo:
            m["BtExamsOnlyCases"] = eo["ours"]["cases"]
            m["BtExamsOnlyOurs"] = f"{eo['ours']['marks_at_k3']:.1f}"
            m["BtExamsOnlyRand"] = f"{eo['random']['marks_at_k3']:.1f}"
            m["BtExamsOnlyCeiling"] = f"{eo['ceiling_mean']:.1f}"
            m["BtExamsOnlyRepeat"] = _pct(eo["repeat_share_of_marks_mean"], 0)
        bm = b.get("borderline_merged", {}).get("summary")
        if bm:
            m["BtBorderRepeat"] = _pct(bm["repeat_share_of_marks_mean"], 0)
            m["BtBorderCeiling"] = f"{bm['ceiling_mean']:.1f}"
            m["BtBorderOurs"] = f"{bm['ours']['marks_at_k3']:.1f}"
            m["BtBorderRand"] = f"{bm['random']['marks_at_k3']:.1f}"
        words = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}
        for n, row in s.get("by_train_papers", {}).items():
            w = words.get(int(n))
            if not w:
                continue
            m[f"BtN{w}Cases"] = row["cases"]
            m[f"BtN{w}Ours"] = f"{row['ours']:.1f}"
            m[f"BtN{w}Rand"] = f"{row['random']:.1f}"
            m[f"BtN{w}Gain"] = f"{row['ours'] - row['random']:.1f}"
            m[f"BtN{w}Ceiling"] = f"{row['ceiling']:.1f}"
            m[f"BtN{w}Repeat"] = _pct(row["repeat_share"], 0)
        # Paired comparisons at k=3 computed the same way as experiments.backtest (exam bootstrap, seed 11)
        import random as _random
        from eval.experiments import _sign_test
        k3 = b["ks"].index(3)

        def _paired(gains):
            rng = _random.Random(11)
            boot = sorted(statistics.mean(gains[rng.randrange(len(gains))] for _ in gains) for _ in range(5000))
            wins, losses = sum(g > 0.05 for g in gains), sum(g < -0.05 for g in gains)
            return {"mean": statistics.mean(gains), "lo": boot[125], "hi": boot[4874], "wins": wins, "losses": losses,
                    "ties": len(gains) - wins - losses, "cases": len(gains), "sign_p": _sign_test(wins, losses)}

        def _put(tag, v):
            m[f"{tag}Mean"], m[f"{tag}Lo"], m[f"{tag}Hi"] = (f"{v[k]:.1f}" for k in ("mean", "lo", "hi"))
            m[f"{tag}Wins"], m[f"{tag}Losses"], m[f"{tag}Ties"], m[f"{tag}Cases"] = v["wins"], v["losses"], v["ties"], v["cases"]
            m[f"{tag}SignP"] = f"{v['sign_p']:.3f}"
        cs = b["cases"]
        for other, tag in (("random", "BtSysGain"), ("frequency", "BtSysVsFreq")):
            _put(tag, _paired([c["curves"]["system_end_to_end"][k3] - c["curves"][other][k3] for c in cs]))
        mid = [c for c in cs if 2 <= len(c["train"]) <= 4]
        if mid:
            _put("BtMidGain", _paired([c["curves"]["ours"][k3] - c["curves"]["random"][k3] for c in mid]))
        if eo and "ours_vs_random_k3" in eo:
            _put("BtExamsOnlyGain", eo["ours_vs_random_k3"])
        # Headroom: share of the random-to-oracle gap that our ranking closes at k=3
        o, r_, q = (s[k]["marks_at_k3"] for k in ("oracle", "random", "ours"))
        m["BtNormGain"] = _pct((q - r_) / (o - r_), 0) if o > r_ else "--"
        m["BtTopicsSeen"] = f"{statistics.mean(v for c in cs for v in c['topics_seen_per_module'].values()):.1f}"
        # Exams needed for the sign test to reach p < 0.05 at the current win share
        v = s.get("ours_vs_random_k3")
        if v and v["wins"] + v["losses"]:
            share = v["wins"] / (v["wins"] + v["losses"])
            m["BtSignNeeded"] = next((n for n in range(1, 500) if _sign_test(round(share * n), n - round(share * n)) < 0.05), "--")
        subjects_bt = sorted({c["subject"] for c in b["cases"]})
        m["BtSubjects"] = len(subjects_bt)
        for key, tag in (("seen_once", "Once"), ("seen_2plus", "TwoPlus"), ("in_last_exam", "Last"),
                         ("not_in_last_exam", "NotLast"), ("all", "All")):
            r = b.get("reappearance", {}).get(key)
            if r:
                m[f"Back{tag}"] = _pct(r["rate"], 0)
                m[f"Back{tag}Lo"] = _pct(r["ci"][0], 0)
                m[f"Back{tag}Hi"] = _pct(r["ci"][1], 0)
                m[f"Back{tag}N"] = r["seen"]
        for key, tag in (("repeat_vs_once", "DiffRepeat"), ("last_vs_not", "DiffLast")):
            r = b.get("reappearance", {}).get(key)
            if r:
                m[f"Back{tag}"] = f"{100 * r['diff']:.0f}"
                m[f"Back{tag}Lo"] = f"{100 * r['lo']:.0f}"
                m[f"Back{tag}Hi"] = f"{100 * r['hi']:.0f}"
        if "reappearance" in b:
            m["BackExams"] = b["reappearance"]["exams"]
        rq = [c["repeated_questions"] / c["test_questions"] for c in b["cases"]]
        m["BtRepeatQMin"] = _pct(min(rq), 0)
        m["BtRepeatQMax"] = _pct(max(rq), 0)
        lines = []
        order = ["oracle", "ours", "system_end_to_end", "frequency", "recency", "marks", "random"]
        for key in order:
            if key not in s:
                continue
            r = s[key]
            lines.append(f"{METHOD[key]} & {r['mean_marks_k1_to_max']:.1f} & {r['marks_at_k3']:.1f} & "
                         f"{r['k_to_pass_mean']:.1f} \\\\" if r["k_to_pass_mean"] is not None else
                         f"{METHOD[key]} & {r['mean_marks_k1_to_max']:.1f} & {r['marks_at_k3']:.1f} & -- \\\\")
        (OUT / "tab_backtest.tex").write_text(
            "\\begin{tabular}{@{}lccc@{}}\n\\toprule\n\\textbf{Ranking} & \\textbf{Mean} & \\textbf{$k{=}3$} & "
            "\\textbf{$k$ to pass} \\\\\n\\midrule\n" + "\n".join(lines) + "\n\\bottomrule\n\\end{tabular}\n", encoding="utf-8")

    # ── Performance ──
    if "perf" in res:
        p = res["perf"]
        for kind, tag in (("native", "Native"), ("scanned", "Scanned")):
            pp = [(e["extract_s"] + e["parse_s"]) / e["pages"] for e in p["extraction"] if e["pdf_type"] == kind]
            if pp:
                m[f"Perf{tag}PerPage"] = f"{statistics.mean(pp):.2f}"
        on, to = p.get("embedding_onnx", {}), p.get("embedding_torch", {})
        if on:
            m["OnnxMB"] = f"{on['model_rss_mb']:.0f}"
            m["OnnxMs"] = f"{on['ms_per_text']:.1f}"
            m["OnnxLoad"] = f"{on['import_and_load_s']:.1f}"
            if "process_rss_mb" in on:
                m["OnnxProcMB"] = f"{on['process_rss_mb']:.1f}"
        if to and "error" not in to:
            m["TorchMB"] = f"{to['model_rss_mb']:.0f}"
            m["TorchMs"] = f"{to['ms_per_text']:.1f}"
            m["TorchLoad"] = f"{to['import_and_load_s']:.1f}"
            if "process_rss_mb" in to:
                m["TorchProcMB"] = f"{to['process_rss_mb']:.1f}"
            m["MemRatio"] = f"{to['model_rss_mb'] / on['model_rss_mb']:.1f}"

    macros = "% Generated by eval/latex.py from eval/results/results.json — do not edit by hand.\n"
    macros += "\n".join(f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in sorted(m.items())) + "\n"
    (OUT / "macros.tex").write_text(macros, encoding="utf-8")
    print(f"  wrote {len(m)} macros and {len(list(OUT.glob('tab_*.tex')))} tables to {OUT}")
