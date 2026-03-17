#!/usr/bin/env python3
"""Generate data.ts for the ai-news-audit website from authoritative Track 1 CSVs.

Reads:
  - data/track1_citation_counts.csv  (outlet × agent citation counts + paywall type)
  - data/track1_agent_summary.csv    (agent-level summary stats)
  - data/track1_citation_matrix.csv  (outlet × agent matrix)
  - data/track1_coded.jsonl          (individual coded responses for knowledge/citation breakdowns)

Writes the Track 1 section of:
  website data.ts
"""

import csv
import json
import sys
from pathlib import Path
from collections import Counter

BRIEF_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = BRIEF_ROOT / "data"
REPO_ROOT = BRIEF_ROOT.parent
WEBSITE_DATA = (
    REPO_ROOT.parent
    / "websites"
    / "app"
    / "src"
    / "app"
    / "[lang]"
    / "innovations"
    / "[slug]"
    / "custom"
    / "ai-news-audit"
    / "data.ts"
)

PAYWALL_MAP = {
    "free": "canadian_free",
    "metered": "canadian_paywalled",
    "hard": "canadian_paywalled",
}

PROVIDER_ORDER = ["anthropic", "openai", "gemini", "xai"]
PROVIDER_LABELS = {
    "anthropic": "Claude",
    "openai": "ChatGPT",
    "gemini": "Gemini",
    "xai": "Grok",
}


def load_citation_matrix() -> dict[str, dict[str, int]]:
    """Load outlet × agent citation matrix."""
    matrix: dict[str, dict[str, int]] = {}
    with open(DATA_DIR / "track1_citation_matrix.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            outlet = row["outlet"]
            matrix[outlet] = {}
            for col in reader.fieldnames[1:]:
                # Column names are like "anthropic (Claude Haiku 4.5)"
                provider = col.split(" (")[0]
                matrix[outlet][provider] = int(row[col])
    return matrix


def load_paywall_types() -> dict[str, str]:
    """Load paywall type for each outlet from citation counts."""
    paywall: dict[str, str] = {}
    with open(DATA_DIR / "track1_citation_counts.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            paywall[row["outlet"]] = row["paywall"]
    return paywall


def load_agent_summary() -> dict[str, dict]:
    """Load agent-level summary statistics."""
    agents = {}
    with open(DATA_DIR / "track1_agent_summary.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            provider = row["provider"]
            agents[provider] = {
                "model": row["model"],
                "successful": int(row["successful_responses"]),
                "citedCanadian": int(row["responses_citing_any_canadian"]),
                "rate": float(row["pct_citing_any_canadian"]),
                "total": int(row["total_requests"]),
                "errors": int(row["error_responses"]),
            }
    return agents


def load_coded_breakdowns() -> dict[str, dict]:
    """Load knowledge_level and citation_type distributions from coded JSONL."""
    records = []
    with open(DATA_DIR / "track1_coded.jsonl") as f:
        for line in f:
            records.append(json.loads(line))

    breakdowns = {}
    for provider in PROVIDER_ORDER:
        rows = [r for r in records if r["provider"] == provider]
        total = len(rows)
        knowledge = Counter(r["knowledge_level"] for r in rows)
        citation = Counter(r["citation_type"] for r in rows)
        breakdowns[provider] = {
            "total_coded": total,
            "knowledge_level": {k: v for k, v in sorted(knowledge.items())},
            "citation_type": {k: v for k, v in sorted(citation.items())},
        }
    return breakdowns


def generate_track1_ts() -> str:
    """Generate TypeScript source for Track 1 data."""
    matrix = load_citation_matrix()
    paywall = load_paywall_types()
    agents = load_agent_summary()
    breakdowns = load_coded_breakdowns()

    lines = []
    lines.append("// Auto-generated from ai_news_audit Track 1 + Track 2 data")
    lines.append(f"// Last generated: {__import__('datetime').datetime.now().isoformat()[:19]}")
    lines.append("")
    lines.append("/* ─── Track 1: Citation Audit (aggregated) ─── */")
    lines.append("")
    lines.append("export interface OutletNode {")
    lines.append("  name: string;")
    lines.append("  type: 'canadian_free' | 'canadian_paywalled' | 'international';")
    lines.append("  mentions: { anthropic: number; openai: number; gemini: number; xai: number; total: number };")
    lines.append("}")
    lines.append("")

    # Build outlet nodes sorted by total descending
    outlets = []
    for outlet, counts in matrix.items():
        total = sum(counts.values())
        pw = paywall.get(outlet, "free")
        outlet_type = PAYWALL_MAP.get(pw, "canadian_free")
        outlets.append((outlet, outlet_type, counts, total))
    outlets.sort(key=lambda x: -x[3])

    lines.append("export const OUTLET_CITATIONS: OutletNode[] = [")
    for name, otype, counts, total in outlets:
        escaped = name.replace("'", "\\'")
        mentions = (
            f"{{ anthropic: {counts.get('anthropic', 0)}, "
            f"openai: {counts.get('openai', 0)}, "
            f"gemini: {counts.get('gemini', 0)}, "
            f"xai: {counts.get('xai', 0)}, "
            f"total: {total} }}"
        )
        lines.append(f"  {{ name: '{escaped}', type: '{otype}', mentions: {mentions} }},")
    lines.append("];")
    lines.append("")

    # Agent citation rates
    lines.append("export const AGENT_CITATION_RATES = {")
    for provider in PROVIDER_ORDER:
        a = agents[provider]
        label = PROVIDER_LABELS[provider]
        lines.append(
            f"  {provider}: {{ label: '{label}', model: '{a['model']}', "
            f"successful: {a['successful']}, citedCanadian: {a['citedCanadian']}, "
            f"rate: {a['rate']} }},"
        )
    lines.append("};")
    lines.append("")

    # Knowledge level breakdown
    lines.append("export const KNOWLEDGE_LEVELS = {")
    for provider in PROVIDER_ORDER:
        b = breakdowns[provider]
        kl = b["knowledge_level"]
        items = ", ".join(f"{k}: {v}" for k, v in kl.items())
        lines.append(f"  {provider}: {{ total: {b['total_coded']}, {items} }},")
    lines.append("};")
    lines.append("")

    # Citation type breakdown
    lines.append("export const CITATION_TYPES = {")
    for provider in PROVIDER_ORDER:
        b = breakdowns[provider]
        ct = b["citation_type"]
        items = ", ".join(f"{k}: {v}" for k, v in ct.items())
        lines.append(f"  {provider}: {{ total: {b['total_coded']}, {items} }},")
    lines.append("};")

    return "\n".join(lines)


def main():
    if not WEBSITE_DATA.exists():
        print(f"Error: Website data file not found at {WEBSITE_DATA}", file=sys.stderr)
        sys.exit(1)

    # Read existing file to preserve everything after auto-generated Track 1
    existing = WEBSITE_DATA.read_text()

    # Find the end-of-Track-1 marker (everything after it is hand-curated / from other sources)
    end_marker = "/* ─── END AUTO-GENERATED Track 1 ─── */"
    end_idx = existing.find(end_marker)
    if end_idx == -1:
        print("Error: Could not find end-of-Track-1 marker in data.ts", file=sys.stderr)
        print("Expected marker: " + end_marker, file=sys.stderr)
        sys.exit(1)

    preserved_section = existing[end_idx:]

    # Generate new Track 1 section
    track1 = generate_track1_ts()

    # Combine: new Track 1 + preserved marker + everything after
    new_content = track1 + "\n\n" + preserved_section
    WEBSITE_DATA.write_text(new_content)

    print(f"Updated {WEBSITE_DATA}")
    print(f"  Outlets: {len(load_citation_matrix())}")
    print(f"  Agents: {len(load_agent_summary())}")


if __name__ == "__main__":
    main()
