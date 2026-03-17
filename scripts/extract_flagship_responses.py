#!/usr/bin/env python3
"""Extract recoverable flagship Track 2 responses from OpenAI batch coding inputs.

The batch coding inputs (sent to GPT-5.2 for LLM-based coding) contain the full
AI agent response text embedded in the user message. We parse these to recover
flagship model responses that were lost from track2_responses.jsonl.

Output: data/track2_flagship_recovered.jsonl
"""

import json
import re
import sys
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"

FLAGSHIP_MODELS = {"Claude Sonnet 4.6", "GPT-5.2", "Gemini 3.1 Pro", "Grok 4"}

MODEL_TO_AGENT = {
    "Claude Sonnet 4.6": "claude",
    "GPT-5.2": "chatgpt",
    "Gemini 3.1 Pro": "gemini",
    "Grok 4": "grok",
}

MODEL_TO_MODEL_ID = {
    "Claude Sonnet 4.6": "claude-sonnet-4-6",
    "GPT-5.2": "gpt-5.2-2025-12-11",
    "Gemini 3.1 Pro": "gemini-3.1-pro",
    "Grok 4": "grok-4",
}

FRAMING_LABELS = {"F1": "Generic", "F2": "Specific", "F3": "Direct"}
CITATION_LABELS = {"C0": "Unprompted", "C1": "Cite sources"}


def parse_user_content(content: str) -> dict:
    """Parse the structured user message from a batch coding input."""
    result = {}

    # Extract outlet
    m = re.search(r"^Outlet:\s*(.+)$", content, re.MULTILINE)
    if m:
        result["source"] = m.group(1).strip()

    # Extract headline
    m = re.search(r"^Headline:\s*(.+)$", content, re.MULTILINE)
    if m:
        result["headline"] = m.group(1).strip()

    # Extract date
    m = re.search(r"^Date:\s*(.+)$", content, re.MULTILINE)
    if m:
        result["date"] = m.group(1).strip()

    # Extract paywall
    m = re.search(r"^Paywall:\s*(.+)$", content, re.MULTILINE)
    if m:
        result["paywall"] = m.group(1).strip().lower() in ("yes", "true")

    # Extract probe prompt
    m = re.search(
        r"PROBE PROMPT \(([^)]+)\):\s*\n(.+?)(?=\n\nAI AGENT RESPONSE)",
        content,
        re.DOTALL,
    )
    if m:
        result["probe_condition"] = m.group(1).strip()
        result["prompt"] = m.group(2).strip()

    # Extract model label and response
    m = re.search(
        r"AI AGENT RESPONSE \(([^)]+)\):\s*\n(.+)",
        content,
        re.DOTALL,
    )
    if m:
        result["model_label"] = m.group(1).strip()
        result["response"] = m.group(2).strip()

    return result


def extract_flagship_responses():
    """Extract all flagship responses from batch coding input files."""
    source_files = [
        DATA_DIR / "track2_coding_batch_input_batch1.jsonl",
        DATA_DIR / "track2_coding_batch_input_recovery.jsonl",
        DATA_DIR / "track2_coding_batch_input.jsonl",
    ]

    # Use batch1 as primary (1327 lines), recovery as fallback for any missing
    seen = {}  # custom_id -> record

    for fpath in source_files:
        if not fpath.exists():
            print(f"  Skipping {fpath.name} (not found)", file=sys.stderr)
            continue

        count = 0
        with open(fpath) as f:
            for line in f:
                entry = json.loads(line)
                custom_id = entry["custom_id"]

                # Skip if already extracted from a previous file
                if custom_id in seen:
                    continue

                user_content = entry["body"]["input"][1]["content"]

                # Find model label
                idx = user_content.find("AI AGENT RESPONSE (")
                if idx < 0:
                    continue
                label_start = idx + len("AI AGENT RESPONSE (")
                label_end = user_content.find(")", label_start)
                model_label = user_content[label_start:label_end]

                if model_label not in FLAGSHIP_MODELS:
                    continue

                # Parse the structured content
                parsed = parse_user_content(user_content)

                # Parse custom_id: article__agent__framing__citation
                parts = custom_id.split("__")
                if len(parts) != 4:
                    print(f"  Unexpected custom_id format: {custom_id}", file=sys.stderr)
                    continue

                article_id, agent_id, framing, citation = parts

                record = {
                    "article_id": article_id,
                    "source": parsed.get("source", ""),
                    "paywall": parsed.get("paywall", False),
                    "headline": parsed.get("headline", ""),
                    "date": parsed.get("date", ""),
                    "agent": MODEL_TO_AGENT[model_label],
                    "agent_label": model_label,
                    "model": MODEL_TO_MODEL_ID[model_label],
                    "tier": "flagship",
                    "framing": framing,
                    "framing_label": FRAMING_LABELS.get(framing, framing),
                    "citation": citation,
                    "citation_label": CITATION_LABELS.get(citation, citation),
                    "prompt": parsed.get("prompt", ""),
                    "response": parsed.get("response", ""),
                    # These fields can't be recovered from batch coding inputs
                    "usage": None,
                    "search_count": None,
                    "cost_usd": None,
                    "citations_from_api": None,
                    "recovered_from": fpath.name,
                }

                seen[custom_id] = record
                count += 1

        print(f"  {fpath.name}: extracted {count} new flagship responses", file=sys.stderr)

    return seen


def main():
    print("Extracting flagship responses from batch coding inputs...", file=sys.stderr)
    recovered = extract_flagship_responses()

    # Summary
    by_agent = {}
    for r in recovered.values():
        agent = r["agent"]
        by_agent[agent] = by_agent.get(agent, 0) + 1

    print(f"\nRecovered {len(recovered)} flagship responses:", file=sys.stderr)
    for agent, count in sorted(by_agent.items()):
        print(f"  {agent}: {count}", file=sys.stderr)

    # Write output
    outpath = DATA_DIR / "track2_flagship_recovered.jsonl"
    with open(outpath, "w") as f:
        for custom_id in sorted(recovered.keys()):
            f.write(json.dumps(recovered[custom_id], ensure_ascii=False) + "\n")

    print(f"\nWritten to {outpath}", file=sys.stderr)
    print(f"Total: {len(recovered)} responses", file=sys.stderr)


if __name__ == "__main__":
    main()
