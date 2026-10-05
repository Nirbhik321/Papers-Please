"""Figures for the paper (IEEE single column = 3.5 in). Vector PDF + PNG preview."""

import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from eval.common import FIGURES  # noqa: E402

COL_W = 3.5
plt.rcParams.update({
    "font.family": "serif", "font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8,
    "legend.fontsize": 7, "xtick.labelsize": 7, "ytick.labelsize": 7,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.alpha": 0.25, "grid.linewidth": 0.5, "lines.linewidth": 1.2, "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02, "pdf.fonttype": 42,
})
# Colour-blind-safe palette (Okabe–Ito)
C = {"ours": "#0072B2", "frequency": "#E69F00", "recency": "#009E73", "marks": "#CC79A7",
     "random": "#999999", "oracle": "#000000", "system_end_to_end": "#D55E00",
     "native": "#0072B2", "scanned": "#E69F00", "p": "#009E73", "r": "#E69F00", "f": "#0072B2"}
NAMES = {"ours": "Ours (frequency × recency)", "frequency": "Frequency only", "recency": "Most recent first",
         "marks": "Highest marks first", "random": "Random order", "oracle": "Hindsight oracle",
         "system_end_to_end": "Ours, end-to-end (system extraction)"}


def _save(fig, name):
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES / f"{name}.pdf")
    fig.savefig(FIGURES / f"{name}.png", dpi=220)
    plt.close(fig)


def extraction(res):
    s = res["summary"]
    metrics = [("f1", "Question\nF1"), ("module_acc", "Module"), ("label_acc", "Q label"),
               ("marks_acc", "Marks"), ("text_sim", "Text\nsimilarity")]
    fig, ax = plt.subplots(figsize=(COL_W, 1.9))
    w = 0.38
    for i, kind in enumerate(["native", "scanned"]):
        if kind not in s:
            continue
        vals = [s[kind][m] for m, _ in metrics]
        xs = [x + (i - 0.5) * w for x in range(len(metrics))]
        bars = ax.bar(xs, vals, w, color=C[kind], label=f"{kind.title()} ({s[kind]['papers']} papers, {s[kind]['gold']} q)")
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.015, f"{v:.2f}", ha="center", va="bottom", fontsize=6)
    ax.set_xticks(range(len(metrics)), [l for _, l in metrics])
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("Score")
    ax.legend(loc="lower left", frameon=False, ncol=2, bbox_to_anchor=(0, 1.0))
    _save(fig, "fig_extraction")


def threshold_sweep(res, production, best):
    fig, ax = plt.subplots(figsize=(COL_W, 2.0))
    for run, style, tag in [(production, "-", "production"), (best, "--", "best")]:
        ts = [r["threshold"] for r in run["sweep"]]
        if tag == "production":
            ax.plot(ts, [r["pairwise"]["precision"] for r in run["sweep"]], style, color=C["p"], label="Precision")
            ax.plot(ts, [r["pairwise"]["recall"] for r in run["sweep"]], style, color=C["r"], label="Recall")
        ax.plot(ts, [r["pairwise"]["f1"] for r in run["sweep"]], style, color=C["f"],
                label=f"F1 — {run['model']} ({run['algorithm']}, {run['variant']})" if tag == "best" else "F1")
    ax.axvline(0.70, color="#555", lw=0.6, ls=":")
    ax.text(0.705, 0.03, "τ = 0.70 (deployed)", fontsize=6, color="#555")
    ax.set_xlabel("Cosine similarity threshold τ")
    ax.set_ylabel("Pairwise score")
    ax.set_ylim(0, 1.02)
    ax.legend(frameon=False, loc="lower left", fontsize=6)
    _save(fig, "fig_threshold")


def models(res):
    best_per_model = {}
    for r in res["runs"]:
        cur = best_per_model.get(r["model"])
        if cur is None or r["loso"]["f1"] > cur["loso"]["f1"]:
            best_per_model[r["model"]] = r
    rows = sorted(best_per_model.values(), key=lambda r: r["loso"]["f1"])
    fig, ax = plt.subplots(figsize=(COL_W, 0.28 * len(rows) + 0.5))
    ys = range(len(rows))
    ax.barh([y + 0.2 for y in ys], [r["best"]["f1"] for r in rows], 0.38, color="#9ecae1", label="F1 at best τ (in-sample)")
    ax.barh([y - 0.2 for y in ys], [r["loso"]["f1"] for r in rows], 0.38, color=C["ours"], label="F1, τ chosen on other subjects")
    for y, r in zip(ys, rows):
        ax.text(max(r["best"]["f1"], r["loso"]["f1"]) + 0.01, y, f"{r['size_mb']:.0f} MB", va="center", fontsize=6)
    ax.set_yticks(list(ys), [r["model"] for r in rows])
    ax.set_xlim(0, 1.08)
    ax.set_xlabel("Pairwise F1 (grouping same-meaning questions)")
    ax.legend(frameon=False, loc="lower right", fontsize=6)
    _save(fig, "fig_models")


def backtest(res):
    ks = res["ks"]
    methods = ["oracle", "ours", "system_end_to_end", "frequency", "recency", "marks", "random"]
    fig, ax = plt.subplots(figsize=(COL_W, 2.3))
    cases = res["cases"]
    for m in methods:
        if not all(m in c["curves"] for c in cases):
            continue
        mean = [statistics.mean(c["curves"][m][i] for c in cases) for i in range(len(ks))]
        ax.plot(ks, mean, "-" if m not in ("oracle", "random") else ":", marker="o" if m == "ours" else None,
                ms=3, color=C[m], label=NAMES[m])
    ceiling = statistics.mean(c["ceiling_all_seen"] for c in cases)
    ax.axhline(ceiling, color="#555", lw=0.6, ls="--")
    ax.text(ks[-1], ceiling + 1.5, "study every topic seen before", ha="right", fontsize=6, color="#555")
    ax.set_xlabel("Topics studied per module (k)")
    ax.set_ylabel("Marks secured in the next exam (/100)")
    ax.set_ylim(0, 105)
    ax.set_title(f"Mean over {len(cases)} held-out exams")
    ax.legend(frameon=False, loc="lower right", fontsize=6)
    _save(fig, "fig_backtest")


def backtest_cases(res):
    ks, cases = res["ks"], res["cases"]
    n = len(cases)
    cols = min(n, 3)
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(2 * COL_W, 1.7 * rows), squeeze=False, sharey=True)
    for ax, c in zip(axes.flat, cases):
        for m in ["oracle", "ours", "system_end_to_end", "frequency", "random"]:
            if m in c["curves"]:
                ax.plot(ks, c["curves"][m], "-" if m not in ("oracle", "random") else ":", color=C[m], label=NAMES[m])
        ax.axhline(c["ceiling_all_seen"], color="#555", lw=0.6, ls="--")
        ax.set_title(f"{c['subject']} — {c['test_session']} (trained on {len(c['train'])})")
        ax.set_xlabel("k per module")
    for ax in axes.flat[n:]:
        ax.axis("off")
    axes[0][0].set_ylabel("Marks (/100)")
    axes.flat[0].legend(frameon=False, fontsize=5.5, loc="lower right")
    _save(fig, "fig_backtest_cases")


def perf(res):
    ex = res["extraction"]
    fig, axes = plt.subplots(1, 2, figsize=(COL_W, 1.7), gridspec_kw={"width_ratios": [1, 1.2]})
    ax = axes[0]
    for i, kind in enumerate(["native", "scanned"]):
        per_page = [(e["extract_s"] + e["parse_s"]) / e["pages"] for e in ex if e["pdf_type"] == kind]
        if per_page:
            ax.bar(i, statistics.mean(per_page), color=C[kind], yerr=statistics.pstdev(per_page), capsize=2)
    ax.set_xticks([0, 1], ["Native", "Scanned"])
    ax.set_ylabel("Seconds per page")
    ax = axes[1]
    onnx, torch = res.get("embedding_onnx", {}), res.get("embedding_torch", {})
    if onnx and torch and "error" not in torch:
        ax.bar([0, 1], [onnx["model_rss_mb"], torch["model_rss_mb"]], color=[C["ours"], "#999"])
        ax.set_xticks([0, 1], ["ONNX", "PyTorch"])
        ax.set_ylabel("Model memory (MB)")
        for x, v, ms in [(0, onnx["model_rss_mb"], onnx["ms_per_text"]), (1, torch["model_rss_mb"], torch["ms_per_text"])]:
            ax.text(x, v, f"{v:.0f} MB\n{ms:.1f} ms/q", ha="center", va="bottom", fontsize=6)
    fig.tight_layout()
    _save(fig, "fig_perf")
