#!/usr/bin/env python3
"""
Intercoder reliability: GPT-5.2 vs Qwen3.5-35B on Track 1 and Track 2 coding.

Computes Cohen's kappa and % agreement for each categorical field.
Outputs a summary table to stdout and saves to data/intercoder_reliability.csv.

Usage:
    uv run python scripts/intercoder_reliability.py
    uv run python scripts/intercoder_reliability.py --track 1
    uv run python scripts/intercoder_reliability.py --track 2
"""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"

# ── Cohen's kappa (unweighted and quadratic-weighted) ───────────────────────

def cohens_kappa(a_labels, b_labels, ordered_categories=None):
    """Compute Cohen's kappa. If ordered_categories provided, uses quadratic weights."""
    assert len(a_labels) == len(b_labels)
    n = len(a_labels)
    if n == 0:
        return float("nan"), 0

    if ordered_categories:
        categories = ordered_categories
    else:
        categories = sorted(set(a_labels) | set(b_labels))
    cat_idx = {c: i for i, c in enumerate(categories)}
    k = len(categories)

    # Filter to only known categories
    pairs = [(a, b) for a, b in zip(a_labels, b_labels)
             if a in cat_idx and b in cat_idx]
    n = len(pairs)
    if n == 0:
        return float("nan"), 0

    # Confusion matrix
    conf = [[0] * k for _ in range(k)]
    for a, b in pairs:
        conf[cat_idx[a]][cat_idx[b]] += 1

    # Quadratic weights: w_ij = 1 - ((i-j)/(k-1))^2
    if ordered_categories and k > 1:
        weights = [[1 - ((i - j) / (k - 1)) ** 2 for j in range(k)] for i in range(k)]
    else:
        weights = [[1 if i == j else 0 for j in range(k)] for i in range(k)]

    row_sums = [sum(conf[i]) for i in range(k)]
    col_sums = [sum(conf[i][j] for i in range(k)) for j in range(k)]

    p_o = sum(weights[i][j] * conf[i][j] for i in range(k) for j in range(k)) / n
    p_e = sum(weights[i][j] * row_sums[i] * col_sums[j]
              for i in range(k) for j in range(k)) / (n * n)

    if p_e == 1.0:
        return 1.0, n
    kappa = (p_o - p_e) / (1.0 - p_e)
    return round(kappa, 4), n


def pct_agree(a_labels, b_labels):
    n = len(a_labels)
    if n == 0:
        return float("nan")
    agree = sum(1 for a, b in zip(a_labels, b_labels) if a == b)
    return round(100 * agree / n, 1)


def kappa_label(k):
    if k is None or k != k:  # nan
        return "n/a"
    if k >= 0.80:
        return "almost perfect"
    if k >= 0.60:
        return "substantial"
    if k >= 0.40:
        return "moderate"
    if k >= 0.20:
        return "fair"
    return "slight/poor"


# ── Track 2 ─────────────────────────────────────────────────────────────────

T2_FIELDS = [
    "reproduction_level",
    "attribution_level",
    "link_quality",
    "factual_accuracy",
    "paywalled_content_reproduced",
]

# Ordinal orderings for weighted kappa (None = nominal, use unweighted)
T2_ORDINAL = {
    "reproduction_level":        ["none", "topic_only", "partial", "close_paraphrase", "verbatim"],
    "attribution_level":         ["none", "vague", "outlet_named", "full"],
    "link_quality":              None,  # nominal
    "factual_accuracy":          ["inaccurate", "unverifiable", "mostly_accurate", "accurate"],
    "paywalled_content_reproduced": None,  # binary
}


def load_track2_gpt():
    """Load GPT coding from track2_coded.csv — keyed by (article_id, agent, framing, citation)."""
    path = DATA_DIR / "track2_coded.csv"
    gpt = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            key = (row["article_id"], row["agent"], row["framing"], row["citation"])
            gpt[key] = {
                "reproduction_level": row.get("llm_reproduction", ""),
                "attribution_level":  row.get("llm_attribution", ""),
                "link_quality":       row.get("llm_link_quality", ""),
                "factual_accuracy":   row.get("llm_accuracy", ""),
                "paywalled_content_reproduced": str(row.get("llm_paywall_reproduced", "")).lower(),
            }
    return gpt


def load_track2_qwen():
    """Load Qwen coding from track2_coded_qwen.jsonl — keyed by custom_id."""
    path = DATA_DIR / "track2_coded_qwen.jsonl"
    qwen = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("error") or not r.get("coding"):
                continue
            # custom_id: article_id__agent__framing__citation
            parts = r["custom_id"].split("__")
            key = tuple(parts[:4])
            c = r["coding"]
            qwen[key] = {
                "reproduction_level": c.get("reproduction_level", ""),
                "attribution_level":  c.get("attribution_level", ""),
                "link_quality":       c.get("link_quality", ""),
                "factual_accuracy":   c.get("factual_accuracy", ""),
                "paywalled_content_reproduced": str(c.get("paywalled_content_reproduced", "")).lower(),
            }
    return qwen


def run_track2():
    print("\n" + "=" * 70)
    print("TRACK 2 — Intercoder Reliability: GPT-5.2 vs Qwen3.5-35B")
    print("=" * 70)

    gpt = load_track2_gpt()
    qwen = load_track2_qwen()

    shared_keys = set(gpt) & set(qwen)
    print(f"GPT coded:   {len(gpt)}")
    print(f"Qwen coded:  {len(qwen)}")
    print(f"Matched:     {len(shared_keys)}\n")

    rows = []
    print(f"  {'Field':<35} {'N':>5}  {'% Agree':>8}  {'κ (unwt)':>9}  {'κ (wt)':>7}  {'Strength (wt)'}")
    print(f"  {'-'*35}  {'-'*5}  {'-'*8}  {'-'*9}  {'-'*7}  {'-'*16}")

    for field in T2_FIELDS:
        a_vals = [gpt[k][field] for k in shared_keys if gpt[k][field] and qwen[k][field]]
        b_vals = [qwen[k][field] for k in shared_keys if gpt[k][field] and qwen[k][field]]
        ordered = T2_ORDINAL.get(field)
        kappa_uw, n = cohens_kappa(a_vals, b_vals)
        kappa_w, _  = cohens_kappa(a_vals, b_vals, ordered_categories=ordered)
        pct = pct_agree(a_vals, b_vals)
        strength = kappa_label(kappa_w)
        print(f"  {field:<35} {n:>5}  {pct:>7.1f}%  {kappa_uw:>9.4f}  {kappa_w:>7.4f}  {strength}")
        rows.append({"track": 2, "field": field, "n": n, "pct_agree": pct,
                     "kappa_unweighted": kappa_uw, "kappa_weighted": kappa_w, "strength": strength})

    # Disagreement breakdown for reproduction_level
    print(f"\n  Reproduction level disagreements (top 10 pairs):")
    pairs = Counter()
    for k in shared_keys:
        a = gpt[k]["reproduction_level"]
        b = qwen[k]["reproduction_level"]
        if a and b and a != b:
            pairs[(a, b)] += 1
    for (a, b), n in pairs.most_common(10):
        print(f"    GPT={a:<20} Qwen={b:<20} n={n}")

    return rows


# ── Track 1 ─────────────────────────────────────────────────────────────────

T1_FIELDS = [
    "knowledge_level",
    "citation_type",
    "accuracy",
    "canadian_sources_cited",
]

T1_ORDINAL = {
    "knowledge_level":       ["no_knowledge", "refusal", "partial", "knowledgeable"],
    "citation_type":         None,  # nominal
    "accuracy":              ["inaccurate", "unverifiable", "mostly_accurate", "accurate"],
    "canadian_sources_cited": None,  # numeric count, treat as nominal for kappa
}

T1_CORPORA = [
    ("economy EN",  "track1_coded.jsonl",              "track1_coded_qwen.jsonl"),
    ("economy FR",  "track1_coded_gpt_fr.jsonl",       "track1_coded_qwen_fr.jsonl"),
    ("flagship EN", "track1_flagship_coded.jsonl",     "track1_flagship_coded_qwen.jsonl"),
    ("flagship FR", "track1_flagship_coded_gpt_fr.jsonl", "track1_flagship_coded_qwen_fr.jsonl"),
]


def load_track1_jsonl(path):
    """Load track1 coded jsonl — keyed by (story_id, provider)."""
    data = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            # GPT files have coding at top level; Qwen files nest under "coding"
            coding = r.get("coding") or r
            if not coding or r.get("error"):
                continue
            key = (r["story_id"], r["provider"])
            data[key] = {
                "knowledge_level":        str(coding.get("knowledge_level", "")),
                "citation_type":          str(coding.get("citation_type", "")),
                "accuracy":               str(coding.get("accuracy", "")),
                "canadian_sources_cited": str(coding.get("canadian_sources_cited", "")),
            }
    return data


def run_track1():
    print("\n" + "=" * 70)
    print("TRACK 1 — Intercoder Reliability: GPT vs Qwen3.5-35B")
    print("=" * 70)

    all_rows = []

    for label, gpt_file, qwen_file in T1_CORPORA:
        gpt_path  = DATA_DIR / gpt_file
        qwen_path = DATA_DIR / qwen_file
        if not gpt_path.exists() or not qwen_path.exists():
            print(f"\n  [{label}] SKIPPED — file(s) missing")
            continue

        gpt  = load_track1_jsonl(gpt_path)
        qwen = load_track1_jsonl(qwen_path)
        shared = set(gpt) & set(qwen)

        print(f"\n  [{label}]  GPT={len(gpt)}  Qwen={len(qwen)}  Matched={len(shared)}")
        print(f"  {'Field':<30} {'N':>5}  {'% Agree':>8}  {'κ (unwt)':>9}  {'κ (wt)':>7}  {'Strength (wt)'}")
        print(f"  {'-'*30}  {'-'*5}  {'-'*8}  {'-'*9}  {'-'*7}  {'-'*16}")

        for field in T1_FIELDS:
            a_vals = [gpt[k][field]  for k in shared if gpt[k][field] and qwen[k][field]]
            b_vals = [qwen[k][field] for k in shared if gpt[k][field] and qwen[k][field]]
            ordered = T1_ORDINAL.get(field)
            kappa_uw, n = cohens_kappa(a_vals, b_vals)
            kappa_w, _  = cohens_kappa(a_vals, b_vals, ordered_categories=ordered)
            pct = pct_agree(a_vals, b_vals)
            strength = kappa_label(kappa_w)
            print(f"  {field:<30} {n:>5}  {pct:>7.1f}%  {kappa_uw:>9.4f}  {kappa_w:>7.4f}  {strength}")
            all_rows.append({"track": 1, "corpus": label, "field": field,
                              "n": n, "pct_agree": pct, "kappa_unweighted": kappa_uw,
                              "kappa_weighted": kappa_w, "strength": strength})

    return all_rows


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--track", type=int, choices=[1, 2],
                        help="Run only track 1 or 2 (default: both)")
    args = parser.parse_args()

    rows = []
    if args.track in (None, 2):
        rows += run_track2()
    if args.track in (None, 1):
        rows += run_track1()

    if rows:
        out = DATA_DIR / "intercoder_reliability.csv"
        fieldnames = sorted(set(k for r in rows for k in r.keys()))
        with open(out, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nSaved → {out}")


if __name__ == "__main__":
    main()
