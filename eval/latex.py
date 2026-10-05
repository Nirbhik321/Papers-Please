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

from eval.common import ROOT, load_gt_groups, load_gt_papers, session_label

OUT = ROOT / "reports" / "generated"
DISPLAY = {"paraphrase-MiniLM-L6-v2": "paraphrase-MiniLM-L6", "all-MiniLM-L6-v2": "all-MiniLM-L6",
           "paraphrase-mpnet-base-v2": "paraphrase-mpnet-base", "all-mpnet-base-v2": "all-mpnet-base",
           "bge-small-en-v1.5": "bge-small-en-v1.5", "gte-small": "gte-small", "e5-small-v2": "e5-small-v2",
           "arctic-embed-xs": "arctic-embed-xs", "mxbai-embed-xsmall-v1": "mxbai-embed-xsmall"}
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
        "\\begin{tabular}{@{}llccc@{}}\n\\toprule\n\\textbf{Code} & \\textbf{Subject} & \\textbf{Papers (scanned)} & "
        "\\textbf{Sub-q.} & \\textbf{Groups (multi)} \\\\\n\\midrule\n" + "\n".join(rows) +
        f"\n\\midrule\n\\textbf{{Total}} & & {m['NumPapers']} ({m['NumScanned']}) & {m['NumQuestions']} & {m['NumGroups']} \\\\\n"
        "\\bottomrule\n\\end{tabular}\n", encoding="utf-8")

    # ── Extraction ──
    if "extraction" in res:
        s = res["extraction"]["summary"]
        lines = []
        for key, label in (("native", "Native text"), ("scanned", "Scanned (OCR)"), ("all", "\\textbf{All}")):
            if key not in s:
                continue
            r = s[key]
            lines.append(f"{label} & {r['papers']} & {r['gold']} & {_f(r['precision'],2)} & {_f(r['recall'],2)} & "
                         f"{_f(r['f1'],2)} & {_f(r['module_acc'],2)} & {_f(r['label_acc'],2)} & {_f(r['marks_acc'],2)} \\\\")
            tag = {"native": "Native", "scanned": "Scanned", "all": "All"}[key]
            for k, v in (("F", r["f1"]), ("P", r["precision"]), ("R", r["recall"]), ("Module", r["module_acc"]),
                         ("Label", r["label_acc"]), ("Marks", r["marks_acc"]), ("Text", r["text_sim"])):
                m[f"Ext{tag}{k}"] = _f(v, 2)
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
        best_per_model = {}
        for r in runs:
            if r["algorithm"] == "complete":
                continue
            cur = best_per_model.get(r["model"])
            if cur is None or r["loso"]["f1"] > cur["loso"]["f1"]:
                best_per_model[r["model"]] = r
        lines = []
        for r in sorted(best_per_model.values(), key=lambda r: -r["loso"]["f1"]):
            lines.append(f"{DISPLAY[r['model']]} & {r['size_mb']:.0f} & {r['algorithm']} & {r['best_threshold']:.3f} & "
                         f"{_f(r['best']['precision'],2)} & {_f(r['best']['recall'],2)} & {_f(r['best']['f1'])} & "
                         f"{_f(r['loso']['f1'])} \\\\")
        (OUT / "tab_models.tex").write_text(
            "\\begin{tabular}{@{}lrlccccc@{}}\n\\toprule\n\\textbf{Model} & \\textbf{MB} & \\textbf{Link.} & $\\boldsymbol{\\tau^*}$ & "
            "\\textbf{P} & \\textbf{R} & \\textbf{F1} & \\textbf{LOSO} \\\\\n\\midrule\n" + "\n".join(lines) +
            "\n\\bottomrule\n\\end{tabular}\n", encoding="utf-8")
        old = next(r for r in runs if r["model"] == "paraphrase-MiniLM-L6-v2" and r["algorithm"] == "greedy" and r["variant"] == "raw")
        new = next(r for r in runs if r["model"] == "mxbai-embed-xsmall-v1" and r["algorithm"] == "average" and r["variant"] == "raw")
        m["OldFAtSeventy"] = _f(old["at_production_threshold"]["f1"])
        m["OldLoso"] = _f(old["loso"]["f1"])
        m["OldBestTau"] = f"{old['best_threshold']:.3f}"
        m["NewLoso"] = _f(new["loso"]["f1"])
        m["NewBestF"] = _f(new["best"]["f1"])
        m["NewTau"] = f"{new['best_threshold']:.3f}"
        m["NewP"] = _f(new["best"]["precision"], 2)
        m["NewR"] = _f(new["best"]["recall"], 2)
        m["NewBcubed"] = _f(new["best_bcubed_f1"])
        m["OldBcubed"] = _f(old["best_bcubed_f1"])
        m["LosoGain"] = f"{100 * (new['loso']['f1'] - old['at_production_threshold']['f1']):.1f}"
        greedy_new = next(r for r in runs if r["model"] == "mxbai-embed-xsmall-v1" and r["algorithm"] == "greedy" and r["variant"] == "raw")
        m["NewGreedyLoso"] = _f(greedy_new["loso"]["f1"])
        focus_drop = [r["loso"]["f1"] - next(x for x in runs if x["model"] == r["model"] and x["algorithm"] == r["algorithm"] and x["variant"] == "raw")["loso"]["f1"]
                      for r in runs if r["variant"] == "focus"]
        m["FocusMeanDrop"] = f"{-100 * statistics.mean(focus_drop):.1f}"
        mp = next(r for r in runs if r["model"] == "all-mpnet-base-v2" and r["algorithm"] == "average" and r["variant"] == "raw")
        m["MpnetLoso"] = _f(mp["loso"]["f1"])
        m["MpnetMB"] = f"{mp['size_mb']:.0f}"
    if "grouping_hybrid" in res:
        for r in res["grouping_hybrid"]["runs"]:
            tag = "New" if r["model"] == "mxbai-embed-xsmall-v1" else "Old"
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
        if to and "error" not in to:
            m["TorchMB"] = f"{to['model_rss_mb']:.0f}"
            m["TorchMs"] = f"{to['ms_per_text']:.1f}"
            m["TorchLoad"] = f"{to['import_and_load_s']:.1f}"
            m["MemRatio"] = f"{to['model_rss_mb'] / on['model_rss_mb']:.1f}"

    macros = "% Generated by eval/latex.py from eval/results/results.json — do not edit by hand.\n"
    macros += "\n".join(f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in sorted(m.items())) + "\n"
    (OUT / "macros.tex").write_text(macros, encoding="utf-8")
    print(f"  wrote {len(m)} macros and {len(list(OUT.glob('tab_*.tex')))} tables to {OUT}")
