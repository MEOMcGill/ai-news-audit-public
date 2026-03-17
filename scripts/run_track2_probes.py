"""
Run Track 2 content theft & attribution probes.

3 framings × 2 citation conditions × 4 agents × N articles.
Each probe is an independent API call (fresh context, no conversation history).
All agents have web search ENABLED — testing the real consumer experience.

Parallelism: 4 providers run concurrently (independent rate limits).
Within each provider, calls are sequential with 1s gap.

Usage:
    uv run python scripts/run_track2_probes.py
    uv run python scripts/run_track2_probes.py --dry-run
    uv run python scripts/run_track2_probes.py --tier economy

Output: data/track2_responses.jsonl
"""

import json
import os
import random
import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ARTICLES_PATH = Path("data/track2_articles.jsonl")
OUTPUT_PATH = Path("data/track2_responses.jsonl")

FRAMINGS = ["F1", "F2", "F3"]
CITATION_CONDITIONS = ["C0", "C1"]
CITATION_SUFFIX = " Please cite your sources."

# Models and pricing (input/output per 1M tokens, search per 1K queries)
AGENTS = {
    "chatgpt": {
        "provider": "openai",
        "model": "gpt-5-mini",
        "label": "GPT-5-mini",
        "pricing": {"input": 0.25, "output": 2.00, "search_per_1k": 30.00},
    },
    "gemini": {
        "provider": "google",
        "model": "gemini-3-flash-preview",
        "label": "Gemini 3 Flash",
        "pricing": {"input": 0.50, "output": 3.00, "search_per_1k": 5.00},
    },
    "claude": {
        "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001",
        "label": "Claude Haiku 4.5",
        "pricing": {"input": 1.00, "output": 5.00, "search_per_1k": 10.00},
    },
    "grok": {
        "provider": "xai",
        "model": "grok-4-fast-non-reasoning",
        "label": "Grok 4 Fast",
        "pricing": {"input": 0.20, "output": 0.50, "search_per_1k": 0.00},
    },
}


def call_openai(model: str, prompt: str) -> dict:
    """OpenAI with web search via Responses API."""
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
    """Anthropic Claude with web search tool."""
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        tools=[
            {
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
            }
        ],
        messages=[{"role": "user", "content": prompt}],
    )

    # Extract text and citations from content blocks
    text_parts = []
    citations = []
    search_count = 0
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
    """Google Gemini with Google Search grounding."""
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

    citations = []
    search_count = 0
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
    """xAI Grok with web search via Responses API."""
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

MAX_RETRIES = 5
BASE_DELAY = 2.0  # seconds


def call_with_retry(fn, model: str, prompt: str, label: str) -> dict:
    """Call provider function with exponential backoff on rate limit / transient errors."""
    for attempt in range(MAX_RETRIES):
        try:
            return fn(model, prompt)
        except Exception as e:
            err_str = str(e).lower()
            retryable = any(kw in err_str for kw in [
                "rate_limit", "rate limit", "429", "quota", "overloaded",
                "503", "529", "500", "server_error", "capacity",
            ])
            if not retryable or attempt == MAX_RETRIES - 1:
                raise
            delay = BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
            print(f"    ↳ {label}: retry {attempt+1}/{MAX_RETRIES} in {delay:.1f}s ({str(e)[:80]})")
            time.sleep(delay)
    raise RuntimeError("unreachable")

# Thread-safe file writer
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
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                articles.append(json.loads(line))
    return articles


def build_prompt(article: dict, framing: str, citation: str) -> str:
    base = article["probes"][framing]
    if citation == "C1":
        base += CITATION_SUFFIX
    return base


def load_existing_responses(path: Path, tier_filter: str | None = None) -> set:
    """Load completed response keys. If tier_filter given, only count matching tier."""
    done = set()
    if path.exists():
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    if tier_filter and r.get("tier", "economy") != tier_filter:
                        continue
                    key = (r["article_id"], r["agent"], r["framing"], r["citation"])
                    done.add(key)
    return done


def run_probes(dry_run: bool = False, tier: str = "economy"):
    articles = load_articles(ARTICLES_PATH)
    done = load_existing_responses(OUTPUT_PATH, tier_filter=tier) if not dry_run else set()

    # Build per-agent job queues: each agent gets its own sequential list
    agent_jobs = {key: [] for key in AGENTS}
    for article in articles:
        for framing in FRAMINGS:
            for citation in CITATION_CONDITIONS:
                prompt = build_prompt(article, framing, citation)
                for agent_key in AGENTS:
                    key = (article["id"], agent_key, framing, citation)
                    if key not in done:
                        agent_jobs[agent_key].append({
                            "article": article,
                            "framing": framing,
                            "citation": citation,
                            "prompt": prompt,
                        })

    total_remaining = sum(len(jobs) for jobs in agent_jobs.values())
    total_all = len(articles) * len(FRAMINGS) * len(CITATION_CONDITIONS) * len(AGENTS)

    print(f"Articles: {len(articles)}")
    print(f"Agents: {', '.join(f'{k} ({v['model']})' for k, v in AGENTS.items())}")
    print(f"Web search: ENABLED on all agents")
    print(f"Total probes: {total_all}")
    print(f"Already completed: {total_all - total_remaining}")
    print(f"Remaining: {total_remaining}")
    for ak, jobs in agent_jobs.items():
        print(f"  {ak}: {len(jobs)} calls")
    print()

    if dry_run:
        for article in articles:
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
        """Run all jobs for one agent sequentially with 1s gap."""
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
                result = call_with_retry(provider_fn, agent_cfg["model"], prompt, label)
                elapsed = time.time() - t0

                search_count = result.get("search_count", 0)
                cost = result.get("cost_actual_usd") or compute_cost(
                    agent_cfg["pricing"], result["usage"], search_count
                )

                record = {
                    "article_id": article["id"],
                    "source": article.get("source", ""),
                    "paywall": article.get("paywall", False),
                    "headline": article.get("headline", ""),
                    "tier": tier,
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
                append_jsonl(OUTPUT_PATH.with_suffix(".errors.jsonl"), error_record)

                with _stats_lock:
                    stats["errors"] += 1

                print(f"  [{i+1}/{len(jobs)}] {label}: ERROR — {str(e)[:100]}")

            # 2s between calls to same provider (was 1s, caused rate limits)
            if i < len(jobs) - 1:
                time.sleep(2)

    # Launch one thread per provider — they run their queues independently
    print("Starting 4 provider threads...\n")
    threads = []
    for agent_key in AGENTS:
        if agent_jobs[agent_key]:
            t = threading.Thread(target=run_agent_queue, args=(agent_key,), name=agent_key)
            threads.append(t)
            t.start()

    for t in threads:
        t.join()

    print(f"\n{'='*60}")
    print(f"DONE")
    print(f"Completed: {stats['completed']}")
    print(f"Errors: {stats['errors']}")
    print(f"Total cost: ${stats['total_cost']:.4f}")
    print(f"Output: {OUTPUT_PATH}")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    tier = "economy"
    for arg in sys.argv:
        if arg.startswith("--tier="):
            tier = arg.split("=", 1)[1]
        elif arg == "--tier" and sys.argv.index(arg) + 1 < len(sys.argv):
            tier = sys.argv[sys.argv.index(arg) + 1]
    run_probes(dry_run=dry_run, tier=tier)
