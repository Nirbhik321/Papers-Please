"""
Figures for the paper (IEEE: single column 3.5 in, Times, text no smaller than 7 pt).
Vector PDF for the paper, PNG for previews. Colours are Okabe-Ito (colour-blind safe);
series that sit close in colour also differ in line style and marker, so every figure
survives greyscale printing.
"""

import random
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from eval.common import FIGURES  # noqa: E402

COL_W = 3.5
plt.rcParams.update({
    "font.family": "serif", "font.serif": ["Times New Roman", "Times", "DejaVu Serif"], "mathtext.fontset": "stix",
    "font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8, "legend.fontsize": 7,
    "xtick.labelsize": 7, "ytick.labelsize": 7,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.axisbelow": True,
    "grid.color": "#e3e3e3", "grid.linewidth": 0.5, "axes.edgecolor": "#444444", "axes.linewidth": 0.6,
    "lines.linewidth": 1.3, "savefig.bbox": "tight", "savefig.pad_inches": 0.02, "pdf.fonttype": 42,
})
INK, MUTED = "#222222", "#666666"
# Okabe–Ito
C = {"ours": "#0072B2", "frequency": "#E69F00", "recency": "#009E73", "marks": "#CC79A7",
     "random": "#999999", "oracle": "#000000", "system_end_to_end": "#D55E00",
     "native": "#0072B2", "scanned": "#E69F00", "heldout": "#009E73", "p": "#009E73", "r": "#E69F00", "f": "#0072B2"}
STYLE = {"oracle": dict(ls=":", marker=None), "ours": dict(ls="-", marker="o"), "system_end_to_end": dict(ls="-.", marker="v"),
         "frequency": dict(ls="--", marker="s"), "recency": dict(ls="-", marker="^"), "marks": dict(ls=(0, (1, 1)), marker="D"),
         "random": dict(ls=":", marker=None)}
NAMES = {"ours": "Ours (frequency × recency)", "frequency": "Frequency only", "recency": "Most recent first",
         "marks": "Highest marks first", "random": "Random order", "oracle": "Hindsight oracle",
         "system_end_to_end": "Ours, end-to-end (system extraction)"}
# Emphasis colours for model comparisons: the deployed model stands out, the rest stay neutral
EMPH = {"deployed": "#0072B2", "original": "#D55E00", "earlier": "#E69F00", "lexical": "#999999", "other": "#555555"}


def _save(fig, name):
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES / f"{name}.pdf")
    fig.savefig(FIGURES / f"{name}.png", dpi=220)
    plt.close(fig)


def _short(model):
    from eval.latex import DISPLAY
    return DISPLAY[model]


def _role(model):
    from eval import embedders
    if model == embedders.DEPLOYED:
        return "deployed"
    if model == embedders.PRODUCTION:
        return "original"
    if model == getattr(embedders, "PREVIOUS_PICK", None):
        return "earlier"
    if model in embedders.LEXICAL:
        return "lexical"
    return "other"


ROLE_LABEL = {"deployed": "Deployed (all-MiniLM-L12)", "original": "Original deployment", "earlier": "Earlier pick (3 subjects)",
              "lexical": "Lexical baseline (no neural model)", "other": "Other embedding models"}


def _best_per_model(runs):
    best = {}
    for r in runs:
        if r["algorithm"] == "complete":
            continue
        cur = best.get(r["model"])
        if cur is None or r["loso"]["f1"] > cur["loso"]["f1"]:
            best[r["model"]] = r
    return best


# ── Extraction ────────────────────────────────────────────────────────────────

def extraction(res):
    s = res["summary"]
    metrics = [("f1", "Question\nF1"), ("module_acc", "Module"), ("label_acc", "Q label"), ("marks_acc", "Marks")]
    groups = [(k, lab) for k, lab in (("native", "Native"), ("scanned", "Scanned"), ("heldout", "Unseen papers")) if k in s]
    fig, ax = plt.subplots(figsize=(COL_W, 1.95))
    w = 0.8 / len(groups)
    for i, (kind, label) in enumerate(groups):
        vals = [s[kind][m] for m, _ in metrics]
        xs = [x + (i - (len(groups) - 1) / 2) * w for x in range(len(metrics))]
        bars = ax.bar(xs, vals, w * 0.92, color=C[kind], label=f"{label} ({s[kind]['papers']} papers, {s[kind]['gold']} q)",
                      hatch="////" if kind == "heldout" else None, edgecolor="white", linewidth=0.4)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.015, f"{v:.2f}", ha="center", va="bottom", fontsize=7, color=INK)
    ax.set_xticks(range(len(metrics)), [l for _, l in metrics])
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Score")
    ax.legend(loc="lower left", frameon=False, ncol=1, bbox_to_anchor=(0, 1.0))
    _save(fig, "fig_extraction")


def extraction_errors(res):
    """Where every printed sub-question ended up, by kind of PDF."""
    s = res["summary"]
    rows = [(k, lab) for k, lab in (("native", "Native"), ("scanned", "Scanned"), ("heldout", "Unseen")) if k in s]
    parts = [("fully_correct", "Found, every field right", "#0072B2", None),
             ("matched_with_errors", "Found, a field wrong", "#E69F00", "////"),
             ("missed", "Missed", "#BBBBBB", None)]
    fig, ax = plt.subplots(figsize=(COL_W, 1.35))
    for y, (kind, label) in enumerate(rows[::-1]):
        o, gold = s[kind]["outcomes"], s[kind]["gold"]
        left = 0.0
        for key, name, color, hatch in parts:
            v = o[key] / gold
            ax.barh(y, v, left=left, color=color, hatch=hatch, edgecolor="white", linewidth=1.2, label=name if y == 0 else None)
            if v > 0.07:
                ax.text(left + v / 2, y, f"{100 * v:.0f}%", ha="center", va="center", fontsize=7,
                        color="white" if color == "#0072B2" else INK)
            left += v
        ax.text(1.01, y, f"+{o['spurious']} spurious", va="center", fontsize=7, color=MUTED)
    ax.set_yticks(range(len(rows)), [lab for _, lab in rows[::-1]])
    ax.set_xlim(0, 1)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1], ["0", "25%", "50%", "75%", "100%"])
    ax.set_xlabel("Share of printed sub-questions")
    ax.grid(axis="y", visible=False)
    ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3, fontsize=7, handlelength=1.2, columnspacing=0.8)
    _save(fig, "fig_extraction_errors")


# ── Grouping ──────────────────────────────────────────────────────────────────

def threshold_sweep(res, production, best):
    fig, ax = plt.subplots(figsize=(COL_W, 2.1))
    old = f"{_short(production['model'])}, {production['algorithm']}"
    ts = [r["threshold"] for r in production["sweep"]]
    ax.plot(ts, [r["pairwise"]["precision"] for r in production["sweep"]], "-", color=C["p"], label=f"Precision ({old})")
    ax.plot(ts, [r["pairwise"]["recall"] for r in production["sweep"]], "--", color=C["r"], label=f"Recall ({old})")
    ax.plot(ts, [r["pairwise"]["f1"] for r in production["sweep"]], "-", color=C["f"], label=f"F1 ({old})")
    bt = [r["threshold"] for r in best["sweep"]]
    ax.plot(bt, [r["pairwise"]["f1"] for r in best["sweep"]], "-.", color=INK,
            label=f"F1 ({_short(best['model'])}, {best['algorithm']})")
    ax.axvline(0.70, color=MUTED, lw=0.6, ls=":")
    ax.text(0.695, 0.04, "original τ = 0.70", fontsize=7, color=MUTED, ha="right")
    ax.set_xlabel("Cosine similarity threshold τ")
    ax.set_ylabel("Pairwise score")
    ax.set_ylim(0, 1.02)
    ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, fontsize=7, columnspacing=1.0)
    _save(fig, "fig_threshold")


def models(res):
    """LOSO pairwise F1 of every model (its best linkage and text variant) with 95% bootstrap CIs."""
    rows = sorted(_best_per_model(res["runs"]).values(), key=lambda r: r["loso"]["f1"])
    fig, ax = plt.subplots(figsize=(COL_W, 0.155 * len(rows) + 0.75))
    seen = set()
    for y, r in enumerate(rows):
        role = _role(r["model"])
        lo, hi = r["loso"].get("ci", (r["loso"]["f1"], r["loso"]["f1"]))
        ax.plot([lo, hi], [y, y], color=EMPH[role], lw=1.0, solid_capstyle="round")
        ax.plot(r["loso"]["f1"], y, "o" if role != "lexical" else "s", ms=4.5 if role != "other" else 3.5, color=EMPH[role],
                mec="white", mew=0.6, label=ROLE_LABEL[role] if role not in seen else None, zorder=3)
        seen.add(role)
        size = "no model" if role == "lexical" else f"{r['size_mb']:.0f} MB"
        ax.text(0.985, y, size, va="center", ha="right", fontsize=7, color=MUTED, transform=ax.get_yaxis_transform())
    ax.set_yticks(range(len(rows)), [f"{_short(r['model'])} ({r['algorithm'][:3]}., {r['variant']})" for r in rows], fontsize=7)
    ax.set_xlim(0.45, 0.88)
    ax.set_xlabel("Pairwise F1, threshold chosen on the other subjects (95% CI)")
    ax.grid(axis="y", visible=False)
    order = [k for k in ("deployed", "original", "earlier", "other", "lexical") if k in seen]
    handles, labels = ax.get_legend_handles_labels()
    lut = dict(zip(labels, handles))
    ax.legend([lut[ROLE_LABEL[k]] for k in order], [ROLE_LABEL[k] for k in order], frameon=False, loc="lower left",
              bbox_to_anchor=(0, 1.0), ncol=2, fontsize=7, handletextpad=0.3, columnspacing=0.8)
    _save(fig, "fig_models")


def models_size(res, budget_mb=150):
    """Accuracy against model size: what the 512 MB server can afford, and what bigger models would add."""
    best = _best_per_model(res["runs"])
    fig, ax = plt.subplots(figsize=(COL_W, 2.25))
    ax.axvspan(40, budget_mb, color="#0072B2", alpha=0.07, lw=0)
    ax.text(43, 0.84, "fits the 512 MB server", fontsize=7, color="#0072B2", va="top")
    lexical = []
    for r in best.values():
        role = _role(r["model"])
        if role == "lexical":
            lexical.append(r)
            continue
        lo, hi = r["loso"].get("ci", (r["loso"]["f1"],) * 2)
        ax.plot([r["size_mb"]] * 2, [lo, hi], color=EMPH[role], lw=0.8, alpha=0.8)
        ax.plot(r["size_mb"], r["loso"]["f1"], "o", ms=5 if role != "other" else 3.8, color=EMPH[role], mec="white", mew=0.6, zorder=3)
    for r in sorted(lexical, key=lambda r: -r["loso"]["f1"]):
        ax.axhline(r["loso"]["f1"], color=EMPH["lexical"], lw=0.8, ls="--", zorder=1)
    if lexical:
        lo_l = min(r["loso"]["f1"] for r in lexical)
        ax.text(1950, lo_l - 0.006, "TF-IDF", fontsize=7, color=MUTED, ha="right", va="top")
    largest = max((r for r in best.values() if _role(r["model"]) != "lexical"), key=lambda r: r["size_mb"])
    ax.annotate(_short(largest["model"]), (largest["size_mb"], largest["loso"]["f1"]), xytext=(-6, 6),
                textcoords="offset points", fontsize=7, color=INK, ha="right")
    from matplotlib.lines import Line2D
    handles = [Line2D([], [], ls="none", marker="o", ms=5, color=EMPH[k], mec="white", label=ROLE_LABEL[k])
               for k in ("deployed", "earlier", "original", "other")]
    handles.append(Line2D([], [], ls="--", color=EMPH["lexical"], lw=0.8, label=ROLE_LABEL["lexical"]))
    ax.legend(handles=handles, frameon=False, loc="lower left", fontsize=7, handletextpad=0.3, borderaxespad=0.2)
    ax.set_xscale("log")
    ax.set_xlim(40, 2000)
    ax.set_xticks([50, 100, 200, 500, 1000, 2000], ["50", "100", "200", "500", "1000", "2000"])
    ax.minorticks_off()
    ax.set_ylim(0.3, 0.85)
    ax.set_xlabel("ONNX model size (MB, log scale)")
    ax.set_ylabel("Pairwise F1 (LOSO)")
    _save(fig, "fig_models_size")


def subject_heatmap(res, n_top=7):
    """Per-subject LOSO F1 for the strongest models plus the reference points."""
    from eval import embedders
    best = _best_per_model(res["runs"])
    subjects = res["subjects"]
    ranked = sorted(best.values(), key=lambda r: -r["loso"]["f1"])
    keep = [r for r in ranked if _role(r["model"]) != "lexical"][:n_top]
    for name in (embedders.DEPLOYED, embedders.PREVIOUS_PICK, embedders.PRODUCTION, "tfidf-char"):
        r = best.get(name)
        if r and r not in keep:
            keep.append(r)
    keep.sort(key=lambda r: -r["loso"]["f1"])
    data = np.array([[r["loso"]["per_subject"][s]["f1"] for s in subjects] + [r["loso"]["f1"]] for r in keep])
    fig, ax = plt.subplots(figsize=(COL_W, 0.2 * len(keep) + 0.75))
    im = ax.imshow(data, cmap="Blues", vmin=0.3, vmax=0.9, aspect="auto")
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            ax.text(j, i, f"{data[i, j]:.2f}", ha="center", va="center", fontsize=7,
                    color="white" if data[i, j] > 0.68 else INK, fontweight="bold" if j == data.shape[1] - 1 else None)
    ax.set_xticks(range(len(subjects) + 1), subjects + ["Pooled"])
    ax.set_yticks(range(len(keep)), [_short(r["model"]) + (" *" if _role(r["model"]) == "deployed" else "") for r in keep])
    ax.axvline(len(subjects) - 0.5, color="white", lw=2)
    ax.tick_params(length=0)
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.xaxis.tick_top()
    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
    cb.ax.tick_params(labelsize=7, length=2)
    cb.outline.set_visible(False)
    _save(fig, "fig_subjects")


def pr_curves(res):
    """Precision against recall as the threshold moves, with each configuration's chosen threshold marked."""
    from eval import embedders
    from modules.deduplicator import SIMILARITY_THRESHOLD
    runs = res["runs"]
    best = _best_per_model(runs)

    def run_of(model, algo, variant="raw"):
        return next((r for r in runs if r["model"] == model and r["algorithm"] == algo and r["variant"] == variant), None)
    others = [r for r in best.values() if _role(r["model"]) == "other"]
    top = max(others, key=lambda r: r["loso"]["f1"]) if others else None
    lines = [(run_of(embedders.DEPLOYED, "average"), SIMILARITY_THRESHOLD, EMPH["deployed"], "-", "o"),
             (run_of(embedders.PRODUCTION, "greedy"), 0.70, EMPH["original"], "--", "s"),
             (top, None, EMPH["other"], "-.", "^"),
             (best.get("tfidf-char"), None, EMPH["lexical"], ":", "D")]
    fig, ax = plt.subplots(figsize=(COL_W, 2.3))
    for run, t_mark, color, ls, mk in lines:
        if not run:
            continue
        pts = [(r["pairwise"]["recall"], r["pairwise"]["precision"], r["threshold"]) for r in run["sweep"]]
        ax.plot([p[0] for p in pts], [p[1] for p in pts], ls=ls, color=color, lw=1.2,
                label=f"{_short(run['model'])} ({run['algorithm'][:3]}.)")
        t_mark = t_mark if t_mark is not None else run["best_threshold"]
        mark = min(pts, key=lambda p: abs(p[2] - t_mark))
        ax.plot(mark[0], mark[1], mk, color=color, ms=5.5, mec="white", mew=0.7, zorder=3)
    for f in (0.5, 0.6, 0.7, 0.8):            # iso-F1 contours
        r_ = np.linspace(f / (2 - f) + 1e-3, 1, 100)
        p_ = f * r_ / (2 * r_ - f)
        ok = (p_ > 0) & (p_ <= 1)
        ax.plot(r_[ok], p_[ok], color="#cccccc", lw=0.5, zorder=0)
        ax.text(r_[ok][-1], p_[ok][-1] + 0.01, f"F1={f}", fontsize=6.5, color="#999999", ha="right", va="bottom")
    ax.set_xlim(0, 1.02)
    ax.set_ylim(0, 1.02)
    ax.set_xlabel("Pairwise recall")
    ax.set_ylabel("Pairwise precision")
    ax.legend(frameon=False, loc="lower left", fontsize=7)
    _save(fig, "fig_pr")


# ── Backtest ──────────────────────────────────────────────────────────────────

def _boot_mean_ci(vals, n=2000, seed=1):
    rng = random.Random(seed)
    means = sorted(statistics.mean(vals[rng.randrange(len(vals))] for _ in vals) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def backtest(res):
    ks = res["ks"]
    methods = ["oracle", "ours", "system_end_to_end", "frequency", "recency", "marks", "random"]
    fig, ax = plt.subplots(figsize=(COL_W, 2.3))
    cases = res["cases"]
    for m in methods:
        if not all(m in c["curves"] for c in cases):
            continue
        per_k = [[c["curves"][m][i] for c in cases] for i in range(len(ks))]
        mean = [statistics.mean(v) for v in per_k]
        if m in ("ours", "random"):
            ci = [_boot_mean_ci(v) for v in per_k]
            ax.fill_between(ks, [a for a, _ in ci], [b for _, b in ci], color=C[m], alpha=0.13, lw=0)
        st = STYLE[m]
        ax.plot(ks, mean, ls=st["ls"], marker=st["marker"], ms=3.2, color=C[m], label=NAMES[m],
                lw=1.5 if m == "ours" else 1.1, zorder=3 if m == "ours" else 2)
    ceiling = statistics.mean(c["ceiling_all_seen"] for c in cases)
    ax.axhline(ceiling, color=MUTED, lw=0.6, ls="--")
    ax.text(ks[-1], ceiling + 1.5, "every topic seen before", ha="right", fontsize=7, color=MUTED)
    ax.axhline(35, color="#bbbbbb", lw=0.6)
    ax.text(ks[-1], 36, "pass mark (35)", ha="right", fontsize=7, color=MUTED)
    ax.set_xlabel("Topics studied per module (k)")
    ax.set_ylabel("Marks secured in the next exam (/100)")
    ax.set_ylim(0, 100)
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(0, -0.2), ncol=2, fontsize=7, columnspacing=1.0)
    _save(fig, "fig_backtest")


def backtest_cases(res):
    ks, cases = res["ks"], res["cases"]
    n = len(cases)
    cols = min(n, 5)
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(2 * COL_W + 0.1, 1.45 * rows + 0.45), squeeze=False, sharey=True, sharex=True)
    for ax, c in zip(axes.flat, cases):
        for m in ["oracle", "ours", "frequency", "random"]:
            if m in c["curves"]:
                st = STYLE[m]
                ax.plot(ks, c["curves"][m], ls=st["ls"], color=C[m], label=NAMES[m], lw=1.1)
        ax.axhline(c["ceiling_all_seen"], color=MUTED, lw=0.5, ls="--")
        ax.set_title(f"{c['subject']} {c['test_session']}\n{len(c['train'])} earlier paper{'s' * (len(c['train']) > 1)}", fontsize=7)
    for ax in axes.flat[n:]:
        ax.axis("off")
    for ax in axes[-1]:
        ax.set_xlabel("k per module")
    for row in axes:
        row[0].set_ylabel("Marks (/100)")
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.legend(handles, labels, frameon=False, fontsize=7, loc="lower center", ncol=len(labels))
    _save(fig, "fig_backtest_cases")


def backtest_growth(res):
    """Gain over random at k=3 against how many earlier papers the ranking had."""
    ks, cases = res["ks"], res["cases"]
    k3 = ks.index(3)
    by_n = {}
    for c in cases:
        by_n.setdefault(len(c["train"]), []).append(c)
    ns = sorted(by_n)
    fig, ax = plt.subplots(figsize=(COL_W, 1.9))
    xs = list(range(len(ns)))
    for key, label, color, dx, mk in (("ceiling", "Ceiling: every seen topic", "#bbbbbb", -0.22, "s"),
                                      ("ours", NAMES["ours"], C["ours"], 0.0, "o"),
                                      ("random", NAMES["random"], C["random"], 0.22, "D")):
        vals = [[c["ceiling_all_seen"] if key == "ceiling" else c["curves"][key][k3] for c in by_n[n]] for n in ns]
        ax.bar([x + dx for x in xs], [statistics.mean(v) for v in vals], 0.2, color=color, label=label,
               edgecolor="white", linewidth=0.6, hatch="////" if key == "random" else None)
        for x, v in zip(xs, vals):
            ax.scatter([x + dx] * len(v), v, s=7, color=INK, zorder=3, linewidths=0, marker=mk)
    ax.set_xticks(xs, [f"{n} earlier\n({len(by_n[n])} exam{'s' * (len(by_n[n]) > 1)})" for n in ns])
    ax.set_ylabel("Marks at k = 3 (/100)")
    ax.set_ylim(0, 100)
    ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3, fontsize=7, columnspacing=0.8, handlelength=1.2)
    _save(fig, "fig_growth")


def reappearance(res):
    """Base rates: how often a topic seen before comes back in the next exam."""
    r = res.get("reappearance")
    if not r:
        return
    pairs = [(("seen_once", "Seen in 1\nearlier paper"), ("seen_2plus", "Seen in 2+\nearlier papers")),
             (("not_in_last_exam", "Not in the\nlast exam"), ("in_last_exam", "In the\nlast exam"))]
    fig, ax = plt.subplots(figsize=(COL_W, 1.9))
    x, ticks, labels = 0, [], []
    for pair in pairs:
        for i, (key, lab) in enumerate(pair):
            v = r[key]
            lo, hi = v["ci"]
            color = "#BBBBBB" if i == 0 else "#0072B2"
            ax.bar(x, v["rate"], 0.62, color=color, edgecolor="white", linewidth=0.6, hatch="////" if i == 0 else None)
            ax.plot([x, x], [lo, hi], color=INK, lw=0.9)
            ax.text(x, hi + 0.012, f"{100 * v['rate']:.0f}%", va="bottom", ha="center", fontsize=7, color=INK)
            ticks.append(x)
            labels.append(f"{lab}\n(n={v['seen']})")
            x += 0.8
        x += 0.6
    ax.set_xticks(ticks, labels, fontsize=7)
    ax.set_ylabel("Came back in the next exam")
    ax.set_ylim(0, max(r[k]["ci"][1] for k in ("seen_2plus", "in_last_exam")) + 0.08)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.grid(axis="x", visible=False)
    _save(fig, "fig_reappearance")


# ── Performance ───────────────────────────────────────────────────────────────

def perf(res):
    ex = res["extraction"]
    fig, axes = plt.subplots(1, 2, figsize=(COL_W, 1.75), gridspec_kw={"width_ratios": [1, 1.2]})
    ax = axes[0]
    for i, kind in enumerate(["native", "scanned"]):
        per_page = [(e["extract_s"] + e["parse_s"]) / e["pages"] for e in ex if e["pdf_type"] == kind]
        if per_page:
            ax.bar(i, statistics.mean(per_page), 0.6, color=C[kind], yerr=statistics.pstdev(per_page), capsize=2,
                   hatch="////" if kind == "scanned" else None, edgecolor="white", linewidth=0.5)
    ax.set_xticks([0, 1], ["Native", "Scanned"])
    ax.set_ylabel("Seconds per page")
    ax.grid(axis="x", visible=False)
    ax = axes[1]
    onnx, torch = res.get("embedding_onnx", {}), res.get("embedding_torch", {})
    if onnx and torch and "error" not in onnx and "error" not in torch:
        ax.bar([0, 1], [onnx["model_rss_mb"], torch["model_rss_mb"]], 0.6, color=[C["ours"], "#999999"],
               edgecolor="white", linewidth=0.5)
        ax.set_xticks([0, 1], ["ONNX", "PyTorch"])
        ax.set_ylabel("Runtime + model memory (MB)")
        ax.set_ylim(0, 1.35 * max(onnx["model_rss_mb"], torch["model_rss_mb"]))
        for x, v, ms in [(0, onnx["model_rss_mb"], onnx["ms_per_text"]), (1, torch["model_rss_mb"], torch["ms_per_text"])]:
            ax.text(x, v, f"{v:.0f} MB\n{ms:.1f} ms/q", ha="center", va="bottom", fontsize=7)
        ax.grid(axis="x", visible=False)
    fig.tight_layout()
    _save(fig, "fig_perf")
