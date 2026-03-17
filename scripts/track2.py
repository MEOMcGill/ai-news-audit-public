#!/usr/bin/env python3
"""
Track 2: Content Theft & Attribution Probe CLI.

3 framings × 2 citation conditions × 4 agents × N articles.
Each probe is an independent API call (fresh context, no conversation history).
All agents have web search ENABLED — testing the real consumer experience.

Usage:
    uv run python scripts/track2.py status              # Show completion status
    uv run python scripts/track2.py run                  # Run remaining probes
    uv run python scripts/track2.py run --agent chatgpt  # Run only ChatGPT probes
    uv run python scripts/track2.py run --dry-run        # Show prompts without calling APIs
    uv run python scripts/track2.py results              # Show fact reproduction & citation results
    uv run python scripts/track2.py results --full       # Include response snippets
    uv run python scripts/track2.py add <article_id>     # Add article from Lexis DB interactively
    uv run python scripts/track2.py export               # Export results to CSV
"""

import argparse
import csv
import json
import os
import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ARTICLES_PATH = Path("data/track2_articles.jsonl")
OUTPUT_PATH = Path("data/track2_responses.jsonl")
ERRORS_PATH = Path("data/track2_responses.errors.jsonl")

FRAMINGS = ["F1", "F2", "F3"]
FRAMING_LABELS = {"F1": "Generic", "F2": "Specific", "F3": "Direct"}
CITATION_CONDITIONS = ["C0", "C1"]
CITATION_LABELS = {"C0": "Unprompted", "C1": "Cite sources"}
CITATION_SUFFIX = " Please cite your sources."

AGENTS_ORDER = ["chatgpt", "gemini", "claude", "grok"]

# Models and pricing (input/output per 1M tokens, search per 1K queries)
AGENTS = {
    "chatgpt": {
        "provider": "openai",
        "model": "gpt-5.2",
        "label": "GPT-5.2",
        "pricing": {"input": 1.75, "output": 14.00, "search_per_1k": 10.00},
    },
    "gemini": {
        "provider": "google",
        "model": "gemini-3.1-pro-preview",
        "label": "Gemini 3.1 Pro",
        "pricing": {"input": 2.00, "output": 12.00, "search_per_1k": 35.00},
    },
    "claude": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "label": "Claude Sonnet 4.6",
        "pricing": {"input": 3.00, "output": 15.00, "search_per_1k": 10.00},
    },
    "grok": {
        "provider": "xai",
        "model": "grok-4-0709",
        "label": "Grok 4",
        "pricing": {"input": 3.00, "output": 15.00, "search_per_1k": 0.00},
    },
}


# ---------------------------------------------------------------------------
# Provider call functions
# ---------------------------------------------------------------------------

def call_openai(model: str, prompt: str) -> dict:
    from openai import OpenAI
    client = OpenAI()
    response = client.responses.create(
        model=model,
        tools=[{"type": "web_search_preview"}],
        input=prompt,
    )
    return {
        "text": response.output_text,
        "model": response.model,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
        "search_count": 1,
    }


def call_anthropic(model: str, prompt: str) -> dict:
    import anthropic
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=16384,
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 5,
            "user_location": {
                "type": "approximate",
                "city": "Montreal",
                "region": "Quebec",
                "country": "CA",
                "timezone": "America/Montreal",
            },
        }],
        messages=[{"role": "user", "content": prompt}],
    )
    text_parts, citations, search_count = [], [], 0
    for block in response.content:
        if hasattr(block, "text"):
            text_parts.append(block.text)
            if hasattr(block, "citations") and block.citations:
                for c in block.citations:
                    citations.append({
                        "url": getattr(c, "url", None),
                        "title": getattr(c, "title", None),
                    })
        if hasattr(block, "type") and block.type == "server_tool_use":
            search_count += 1
    return {
        "text": "\n".join(text_parts),
        "model": response.model,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
        "search_count": search_count,
        "citations": citations,
    }


def call_google(model: str, prompt: str) -> dict:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        ),
    )
    citations, search_count = [], 0
    if response.candidates and response.candidates[0].grounding_metadata:
        meta = response.candidates[0].grounding_metadata
        search_count = len(meta.web_search_queries) if meta.web_search_queries else 0
        if meta.grounding_chunks:
            for chunk in meta.grounding_chunks:
                if hasattr(chunk, "web") and chunk.web:
                    citations.append({"url": chunk.web.uri, "title": chunk.web.title})
    return {
        "text": response.text,
        "model": model,
        "usage": {
            "input_tokens": getattr(response.usage_metadata, "prompt_token_count", None),
            "output_tokens": getattr(response.usage_metadata, "candidates_token_count", None),
        },
        "search_count": search_count,
        "citations": citations,
    }


def call_xai(model: str, prompt: str) -> dict:
    from openai import OpenAI
    client = OpenAI(
        api_key=os.environ["XAI_API_KEY"],
        base_url="https://api.x.ai/v1",
    )
    response = client.responses.create(
        model=model,
        tools=[{"type": "web_search"}],
        input=[{"role": "user", "content": prompt}],
    )
    return {
        "text": response.output_text,
        "model": model,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
        "search_count": getattr(response.usage, "num_server_side_tools_used", 0) or 0,
    }


PROVIDER_FNS = {
    "openai": call_openai,
    "anthropic": call_anthropic,
    "google": call_google,
    "xai": call_xai,
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_write_lock = threading.Lock()


def append_jsonl(path: Path, record: dict):
    with _write_lock:
        with open(path, "a") as f:
            f.write(json.dumps(record) + "\n")


def compute_cost(pricing: dict, usage: dict, search_count: int) -> float:
    input_cost = (usage.get("input_tokens") or 0) / 1_000_000 * pricing.get("input", 0)
    output_cost = (usage.get("output_tokens") or 0) / 1_000_000 * pricing.get("output", 0)
    search_cost = search_count / 1000 * pricing.get("search_per_1k", 0)
    return round(input_cost + output_cost + search_cost, 6)


def load_articles(path: Path) -> list[dict]:
    articles = []
    if not path.exists():
        return articles
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                articles.append(json.loads(line))
    return articles


def load_responses(path: Path) -> list[dict]:
    records = []
    if not path.exists():
        return records
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_done_keys(path: Path) -> set:
    done = set()
    for r in load_responses(path):
        done.add((r["article_id"], r["agent"], r["framing"], r["citation"]))
    return done


def build_prompt(article: dict, framing: str, citation: str) -> str:
    base = article["probes"][framing]
    if citation == "C1":
        base += CITATION_SUFFIX
    return base


def check_fact(resp_lower: str, pattern) -> bool:
    if isinstance(pattern, list):
        return any(p in resp_lower for p in pattern)
    return pattern in resp_lower


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_status(args):
    """Show completion status for all articles × agents × conditions."""
    articles = load_articles(ARTICLES_PATH)
    done = load_done_keys(OUTPUT_PATH)
    responses = load_responses(OUTPUT_PATH)

    if not articles:
        print("No articles in", ARTICLES_PATH)
        return

    total_expected = len(articles) * len(FRAMINGS) * len(CITATION_CONDITIONS) * len(AGENTS)
    total_done = len(done)
    total_cost = sum(r.get("cost_usd", 0) for r in responses)

    print(f"Articles: {len(articles)}")
    print(f"Design: {len(FRAMINGS)} framings × {len(CITATION_CONDITIONS)} citations × {len(AGENTS)} agents = {len(FRAMINGS) * len(CITATION_CONDITIONS) * len(AGENTS)} probes/article")
    print(f"Total probes: {total_expected}")
    print(f"Completed: {total_done}/{total_expected} ({100*total_done/total_expected:.0f}%)")
    print(f"Total cost: ${total_cost:.4f}")
    print()

    # Per-article × agent matrix
    for article in articles:
        paywall_tag = "PAYWALL" if article.get("paywall") else "FREE"
        print(f"  {article['id']} ({article['source']}, {paywall_tag})")
        for agent in AGENTS_ORDER:
            n_done = sum(
                1 for f in FRAMINGS for c in CITATION_CONDITIONS
                if (article["id"], agent, f, c) in done
            )
            n_total = len(FRAMINGS) * len(CITATION_CONDITIONS)
            status = "✓" if n_done == n_total else f"{n_done}/{n_total}"
            print(f"    {agent:8s}: {status}")
        print()

    # Check for errors
    if ERRORS_PATH.exists():
        errors = load_responses(ERRORS_PATH)
        if errors:
            print(f"Errors logged: {len(errors)} (see {ERRORS_PATH})")


def cmd_run(args):
    """Run remaining probes (or specific subset)."""
    articles = load_articles(ARTICLES_PATH)
    if not articles:
        print("No articles in", ARTICLES_PATH)
        return

    done = load_done_keys(OUTPUT_PATH) if not args.dry_run else set()

    # Filter agents if specified
    agent_filter = set()
    if args.agent:
        for a in args.agent:
            if a not in AGENTS:
                print(f"Unknown agent: {a}. Available: {', '.join(AGENTS.keys())}")
                return
            agent_filter.add(a)
    else:
        agent_filter = set(AGENTS.keys())

    # Filter articles if specified
    article_filter = None
    if args.article:
        article_ids = {a["id"] for a in articles}
        for aid in args.article:
            if aid not in article_ids:
                print(f"Unknown article: {aid}. Available: {', '.join(article_ids)}")
                return
        article_filter = set(args.article)

    # Build per-agent job queues
    agent_jobs = {key: [] for key in AGENTS if key in agent_filter}
    for article in articles:
        if article_filter and article["id"] not in article_filter:
            continue
        for framing in FRAMINGS:
            for citation in CITATION_CONDITIONS:
                prompt = build_prompt(article, framing, citation)
                for agent_key in agent_jobs:
                    key = (article["id"], agent_key, framing, citation)
                    if key not in done:
                        agent_jobs[agent_key].append({
                            "article": article,
                            "framing": framing,
                            "citation": citation,
                            "prompt": prompt,
                        })

    total_remaining = sum(len(jobs) for jobs in agent_jobs.values())

    print(f"Articles: {len(articles)}")
    print(f"Agents: {', '.join(f'{k} ({AGENTS[k]['model']})' for k in agent_jobs)}")
    print(f"Web search: ENABLED on all agents")
    print(f"Remaining: {total_remaining}")
    for ak, jobs in agent_jobs.items():
        print(f"  {ak}: {len(jobs)} calls")
    print()

    if total_remaining == 0:
        print("All probes complete!")
        return

    if args.dry_run:
        for article in articles:
            if article_filter and article["id"] not in article_filter:
                continue
            for framing in FRAMINGS:
                for citation in CITATION_CONDITIONS:
                    prompt = build_prompt(article, framing, citation)
                    print(f"--- {article['id']} | {framing} | {citation} ---")
                    print(f"  {prompt}")
                    print()
        return

    # Shared counters
    stats = {"completed": 0, "errors": 0, "total_cost": 0.0}
    _stats_lock = threading.Lock()

    def run_agent_queue(agent_key: str):
        agent_cfg = AGENTS[agent_key]
        provider_fn = PROVIDER_FNS[agent_cfg["provider"]]
        jobs = agent_jobs[agent_key]

        for i, job in enumerate(jobs):
            article = job["article"]
            framing = job["framing"]
            citation = job["citation"]
            prompt = job["prompt"]
            label = f"{agent_key} | {article['id']} | {framing} | {citation}"

            try:
                t0 = time.time()
                result = provider_fn(agent_cfg["model"], prompt)
                elapsed = time.time() - t0

                search_count = result.get("search_count", 0)
                cost = compute_cost(
                    agent_cfg["pricing"], result["usage"], search_count
                )

                record = {
                    "article_id": article["id"],
                    "source": article["source"],
                    "paywall": article["paywall"],
                    "headline": article["headline"],
                    "agent": agent_key,
                    "agent_label": agent_cfg["label"],
                    "model": result["model"],
                    "framing": framing,
                    "citation": citation,
                    "prompt": prompt,
                    "response": result["text"],
                    "usage": result["usage"],
                    "search_count": search_count,
                    "cost_usd": round(cost, 6),
                    "citations_from_api": result.get("citations", []),
                    "elapsed_s": round(elapsed, 2),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                append_jsonl(OUTPUT_PATH, record)

                with _stats_lock:
                    stats["completed"] += 1
                    stats["total_cost"] += cost

                tokens_in = result["usage"].get("input_tokens", "?")
                tokens_out = result["usage"].get("output_tokens", "?")
                print(f"  [{i+1}/{len(jobs)}] {label}: OK ({elapsed:.1f}s, in={tokens_in} out={tokens_out}, ${cost:.4f})")

            except Exception as e:
                error_record = {
                    "article_id": article["id"],
                    "agent": agent_key,
                    "framing": framing,
                    "citation": citation,
                    "prompt": prompt,
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                append_jsonl(ERRORS_PATH, error_record)

                with _stats_lock:
                    stats["errors"] += 1

                print(f"  [{i+1}/{len(jobs)}] {label}: ERROR — {str(e)[:100]}")

            if i < len(jobs) - 1:
                time.sleep(1)

    # Launch one thread per provider
    print(f"Starting {sum(1 for j in agent_jobs.values() if j)} provider threads...\n")
    threads = []
    for agent_key in AGENTS:
        if agent_key in agent_jobs and agent_jobs[agent_key]:
            t = threading.Thread(target=run_agent_queue, args=(agent_key,), name=agent_key)
            threads.append(t)
            t.start()

    for t in threads:
        t.join()

    print(f"\n{'='*60}")
    print(f"DONE — Completed: {stats['completed']}, Errors: {stats['errors']}, Cost: ${stats['total_cost']:.4f}")


def cmd_results(args):
    """Show fact reproduction and source citation results."""
    articles = load_articles(ARTICLES_PATH)
    records = load_responses(OUTPUT_PATH)

    if not records:
        print("No responses yet. Run: uv run python scripts/track2.py run")
        return

    # Build fact-checking patterns from articles
    article_facts = {}
    article_sources = {}
    for article in articles:
        aid = article["id"]
        article_sources[aid] = article["source"].lower()
        # Build patterns from distinctive_facts
        # These are hardcoded for now since they require manual identification
        # of substring patterns from the article's distinctive facts

    for article in articles:
        aid = article["id"]
        paywall_tag = "PAYWALL" if article.get("paywall") else "FREE"
        print(f"\n{'='*80}")
        print(f" {article['source']}: {article['headline'][:60]}... ({paywall_tag})")
        print(f"{'='*80}")

        for framing in FRAMINGS:
            for citation in CITATION_CONDITIONS:
                header = f"{FRAMING_LABELS[framing]} | {CITATION_LABELS[citation]}"
                print(f"\n  --- {header} ---")

                for agent in AGENTS_ORDER:
                    matches = [
                        r for r in records
                        if r["article_id"] == aid
                        and r["agent"] == agent
                        and r["framing"] == framing
                        and r["citation"] == citation
                    ]
                    if not matches:
                        print(f"    {agent:8s}: [MISSING]")
                        continue

                    r = matches[0]
                    resp_lower = r["response"].lower()
                    citations_api = r.get("citations_from_api", [])

                    # Check source citation
                    source_name = article_sources.get(aid, "")
                    # Use short names for matching
                    source_short = {
                        "the toronto star": "toronto star",
                        "cbc (news)": "cbc",
                        "cbc news": "cbc",
                        "montreal gazette": "gazette",
                        "the gazette (montreal)": "gazette",
                        "radio-canada": "radio-canada",
                        "radio-canada (news)": "radio-canada",
                        "la presse canadienne": "la presse canadienne",
                        "national post (f/k/a the financial post) (canada)": "national post",
                        "the logic": "the logic",
                    }.get(source_name, source_name)

                    api_cited = any(
                        source_short in (c.get("url", "") or "").lower()
                        or source_short in (c.get("title", "") or "").lower()
                        for c in citations_api
                    )
                    text_cited = source_short in resp_lower

                    if api_cited and text_cited:
                        cite_str = "YES (API+text)"
                    elif api_cited:
                        cite_str = "YES (API only)"
                    elif text_cited:
                        cite_str = "YES (text only)"
                    else:
                        cite_str = "NO"

                    tokens_in = r.get("usage", {}).get("input_tokens", "?")
                    tokens_out = r.get("usage", {}).get("output_tokens", "?")
                    n_api_cites = len(citations_api)

                    print(
                        f"    {agent:8s}: source cited={cite_str} | "
                        f"API citations={n_api_cites} | "
                        f"${r['cost_usd']:.4f} | "
                        f"in={tokens_in} out={tokens_out}"
                    )

                    # Show API citation URLs
                    if citations_api and args.full:
                        for c in citations_api[:5]:
                            url = c.get("url", "")
                            title = (c.get("title", "") or "")[:60]
                            print(f"              cite: {title} | {url}")

                    # Show response snippet
                    if args.full:
                        snippet = r["response"][:250].replace("\n", " ")
                        print(f"              >>> {snippet}...")

        print()


def cmd_export(args):
    """Export results to CSV for analysis."""
    articles = load_articles(ARTICLES_PATH)
    records = load_responses(OUTPUT_PATH)

    if not records:
        print("No responses yet.")
        return

    article_map = {a["id"]: a for a in articles}
    out_path = args.output or "data/track2_results.csv"

    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "article_id", "source", "paywall", "agent", "agent_label", "model",
            "framing", "framing_label", "citation", "citation_label",
            "response_length", "input_tokens", "output_tokens",
            "search_count", "cost_usd", "n_api_citations",
            "source_cited_api", "source_cited_text", "elapsed_s",
            "response",
        ])

        for r in records:
            aid = r["article_id"]
            article = article_map.get(aid, {})
            source_name = article.get("source", "").lower()
            source_short = {
                "the toronto star": "toronto star",
                "cbc news": "cbc",
                "montreal gazette": "gazette",
                "radio-canada": "radio-canada",
            }.get(source_name, source_name)

            resp_lower = r["response"].lower()
            citations_api = r.get("citations_from_api", [])

            api_cited = any(
                source_short in (c.get("url", "") or "").lower()
                or source_short in (c.get("title", "") or "").lower()
                for c in citations_api
            )
            text_cited = source_short in resp_lower

            writer.writerow([
                r["article_id"],
                r.get("source", ""),
                r.get("paywall", ""),
                r["agent"],
                r.get("agent_label", ""),
                r.get("model", ""),
                r["framing"],
                FRAMING_LABELS.get(r["framing"], ""),
                r["citation"],
                CITATION_LABELS.get(r["citation"], ""),
                len(r.get("response", "")),
                r.get("usage", {}).get("input_tokens", ""),
                r.get("usage", {}).get("output_tokens", ""),
                r.get("search_count", 0),
                r.get("cost_usd", 0),
                len(citations_api),
                api_cited,
                text_cited,
                r.get("elapsed_s", ""),
                r.get("response", ""),
            ])

    print(f"Exported {len(records)} rows to {out_path}")


def cmd_add(args):
    """Add an article from the Lexis DB to the probe set."""
    import sqlite3

    db_path = Path("data/lexis_articles.db")
    if not db_path.exists():
        print("Lexis DB not found at", db_path)
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    if args.search:
        # Search by headline
        rows = conn.execute(
            "SELECT id, headline, source, date, word_count FROM articles "
            "WHERE headline LIKE ? ORDER BY word_count DESC LIMIT 20",
            (f"%{args.search}%",)
        ).fetchall()
        if not rows:
            print(f"No articles matching '{args.search}'")
            return
        print(f"Matching articles ({len(rows)}):\n")
        for r in rows:
            print(f"  [{r['id']:4d}] {r['source']:20s} | {r['date']} | {r['word_count']:5d}w | {r['headline'][:60]}")
        print(f"\nUse: uv run python scripts/track2.py add --id <ID> to select one")
        return

    if not args.id:
        print("Provide --search <term> or --id <db_id>")
        return

    row = conn.execute(
        "SELECT * FROM articles WHERE id = ?", (args.id,)
    ).fetchone()
    if not row:
        print(f"Article ID {args.id} not found")
        return

    print(f"\nArticle: {row['headline']}")
    print(f"Source: {row['source']} | Date: {row['date']} | Words: {row['word_count']}")
    print(f"\nBody preview:\n{row['body'][:500]}...\n")

    # Check if already added
    existing = load_articles(ARTICLES_PATH)
    existing_ids = {a["id"] for a in existing}

    article_id = args.article_id or input("Enter article_id (short slug, e.g. 'star_housing_crisis'): ").strip()
    if article_id in existing_ids:
        print(f"Article '{article_id}' already exists in {ARTICLES_PATH}")
        return

    paywall = row["source"] in ("The Toronto Star", "Montreal Gazette")

    print(f"\nPaywall: {paywall}")
    print("\nYou need to provide:")
    print("  1. Three probe prompts (F1=Generic, F2=Specific, F3=Direct)")
    print("  2. 5-8 distinctive facts for measuring reproduction")
    print(f"\nArticle added with ID '{article_id}'. Edit {ARTICLES_PATH} to add probes and facts.")

    record = {
        "id": article_id,
        "source": row["source"],
        "paywall": paywall,
        "headline": row["headline"],
        "date": row["date"],
        "word_count": row["word_count"],
        "distinctive_facts": [],
        "probes": {"F1": "", "F2": "", "F3": ""},
        "lexis_db_id": row["id"],
    }

    with open(ARTICLES_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")

    print(f"\nAdded to {ARTICLES_PATH}. Edit the file to fill in probes and distinctive_facts.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Track 2: Content Theft & Attribution Probe",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command")

    # status
    sub.add_parser("status", help="Show completion status")

    # run
    p_run = sub.add_parser("run", help="Run remaining probes")
    p_run.add_argument("--dry-run", action="store_true", help="Show prompts without calling APIs")
    p_run.add_argument("--agent", nargs="+", help="Only run specific agents (e.g. chatgpt gemini)")
    p_run.add_argument("--article", nargs="+", help="Only run specific articles by ID")

    # results
    p_results = sub.add_parser("results", help="Show fact reproduction & citation results")
    p_results.add_argument("--full", action="store_true", help="Include response snippets and citation URLs")

    # export
    p_export = sub.add_parser("export", help="Export results to CSV")
    p_export.add_argument("--output", "-o", help="Output CSV path (default: data/track2_results.csv)")

    # add
    p_add = sub.add_parser("add", help="Add article from Lexis DB")
    p_add.add_argument("--search", "-s", help="Search articles by headline keyword")
    p_add.add_argument("--id", type=int, help="Select article by Lexis DB ID")
    p_add.add_argument("--article-id", help="Short slug ID for the article")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    {
        "status": cmd_status,
        "run": cmd_run,
        "results": cmd_results,
        "export": cmd_export,
        "add": cmd_add,
    }[args.command](args)


if __name__ == "__main__":
    main()
