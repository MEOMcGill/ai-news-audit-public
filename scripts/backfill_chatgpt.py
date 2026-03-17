"""Fast concurrent backfill for ChatGPT only."""
import json
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

ARTICLES_PATH = Path("data/track2_articles.jsonl")
OUTPUT_PATH = Path("data/track2_responses.jsonl")
FRAMINGS = ["F1", "F2", "F3"]
CITATION_CONDITIONS = ["C0", "C1"]
CITATION_SUFFIX = " Please cite your sources."
CONCURRENCY = 8

MODEL = "gpt-5-mini"
PRICING = {"input": 0.25, "output": 2.00, "search_per_1k": 30.00}

_write_lock = threading.Lock()


def append_jsonl(path, record):
    with _write_lock:
        with open(path, "a") as f:
            f.write(json.dumps(record) + "\n")


def call_openai(prompt):
    from openai import OpenAI
    client = OpenAI()
    response = client.responses.create(
        model=MODEL,
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


def compute_cost(usage, search_count):
    inp = (usage.get("input_tokens") or 0) / 1e6 * PRICING["input"]
    out = (usage.get("output_tokens") or 0) / 1e6 * PRICING["output"]
    search = search_count / 1000 * PRICING["search_per_1k"]
    return round(inp + out + search, 6)


def run_one(job):
    article, framing, citation, prompt = job
    label = f"{article['id']} | {framing} | {citation}"
    max_retries = 5
    for attempt in range(max_retries):
        try:
            t0 = time.time()
            result = call_openai(prompt)
            elapsed = time.time() - t0
            cost = compute_cost(result["usage"], result["search_count"])
            record = {
                "article_id": article["id"],
                "source": article.get("source", ""),
                "paywall": article.get("paywall", False),
                "headline": article.get("headline", ""),
                "tier": "economy",
                "agent": "chatgpt",
                "agent_label": "GPT-5-mini",
                "model": result["model"],
                "framing": framing,
                "citation": citation,
                "prompt": prompt,
                "response": result["text"],
                "usage": result["usage"],
                "search_count": result["search_count"],
                "cost_usd": cost,
                "citations_from_api": [],
                "elapsed_s": round(elapsed, 2),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            append_jsonl(OUTPUT_PATH, record)
            return True, label, cost, elapsed
        except Exception as e:
            err = str(e).lower()
            retryable = any(k in err for k in ["429", "rate", "quota", "500", "503", "overload"])
            if not retryable or attempt == max_retries - 1:
                append_jsonl(OUTPUT_PATH.with_suffix(".errors.jsonl"), {
                    "article_id": article["id"], "agent": "chatgpt",
                    "framing": framing, "citation": citation,
                    "prompt": prompt, "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                return False, label, 0, 0
            delay = (2 ** attempt) + 1
            print(f"  retry {attempt+1} for {label} in {delay}s")
            time.sleep(delay)
    return False, label, 0, 0


def main():
    # Load articles
    articles = []
    with open(ARTICLES_PATH) as f:
        for line in f:
            if line.strip():
                articles.append(json.loads(line))

    # Load done
    done = set()
    with open(OUTPUT_PATH) as f:
        for line in f:
            r = json.loads(line.strip())
            if r.get("tier", "economy") == "economy" and r["agent"] == "chatgpt":
                done.add((r["article_id"], r["framing"], r["citation"]))

    # Build jobs
    jobs = []
    for article in articles:
        for framing in FRAMINGS:
            for citation in CITATION_CONDITIONS:
                if (article["id"], framing, citation) not in done:
                    prompt = article["probes"][framing]
                    if citation == "C1":
                        prompt += CITATION_SUFFIX
                    jobs.append((article, framing, citation, prompt))

    print(f"ChatGPT backfill: {len(jobs)} remaining, concurrency={CONCURRENCY}")

    completed = 0
    errors = 0
    total_cost = 0.0

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = {pool.submit(run_one, job): job for job in jobs}
        for future in as_completed(futures):
            ok, label, cost, elapsed = future.result()
            if ok:
                completed += 1
                total_cost += cost
                print(f"  [{completed}/{len(jobs)}] {label}: OK ({elapsed:.1f}s, ${cost:.4f})")
            else:
                errors += 1
                print(f"  [{completed}/{len(jobs)}] {label}: FAILED")

    print(f"\nDONE: {completed} completed, {errors} errors, ${total_cost:.2f}")


if __name__ == "__main__":
    main()
