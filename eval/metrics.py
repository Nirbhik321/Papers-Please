"""Matching extracted questions to ground truth, and clustering metrics."""

from difflib import SequenceMatcher
from itertools import combinations

from eval.common import norm_text


def text_sim(a: str, b: str) -> float:
    a, b = norm_text(a), norm_text(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def match_questions(gt: list[dict], sys: list[dict], min_sim: float = 0.5):
    """
    One-to-one greedy matching on text similarity (highest first).
    Returns (pairs [(gt_idx, sys_idx, sim)], unmatched_gt, unmatched_sys).
    """
    cands = sorted(
        ((text_sim(g["text"], s["text"]), i, j) for i, g in enumerate(gt) for j, s in enumerate(sys)),
        reverse=True,
    )
    used_g, used_s, pairs = set(), set(), []
    for sim, i, j in cands:
        if sim < min_sim:
            break
        if i in used_g or j in used_s:
            continue
        used_g.add(i)
        used_s.add(j)
        pairs.append((i, j, sim))
    return pairs, [i for i in range(len(gt)) if i not in used_g], [j for j in range(len(sys)) if j not in used_s]


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": p, "recall": r, "f1": f, "tp": tp, "fp": fp, "fn": fn}


def pair_counts(gold: list, pred: list) -> tuple[int, int, int]:
    """Pairwise TP/FP/FN: a pair is positive when both items share a cluster."""
    tp = fp = fn = 0
    for i, j in combinations(range(len(gold)), 2):
        g, p = gold[i] == gold[j], pred[i] == pred[j]
        tp += g and p
        fp += p and not g
        fn += g and not p
    return tp, fp, fn


def bcubed(gold: list, pred: list) -> dict:
    n = len(gold)
    if not n:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    p_sum = r_sum = 0.0
    for i in range(n):
        same_pred = [j for j in range(n) if pred[j] == pred[i]]
        same_gold = [j for j in range(n) if gold[j] == gold[i]]
        both = sum(1 for j in same_pred if gold[j] == gold[i])
        p_sum += both / len(same_pred)
        r_sum += both / len(same_gold)
    p, r = p_sum / n, r_sum / n
    return {"precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0}
