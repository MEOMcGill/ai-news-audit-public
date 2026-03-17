"""
Batch-code Track 1 and Track 2 responses via OpenAI or Gemini Batch API.

Supports two reviewers (same coding prompts, different LLM coder):
  --reviewer gpt    → GPT-5.2 via OpenAI Batch API (50% discount)
  --reviewer gemini → Gemini 3.1 Pro via Google Batch API (50% discount)

Usage:
    python scripts/code_batch.py prepare track1 --reviewer gpt
    python scripts/code_batch.py prepare track1 --reviewer gemini --tier flagship
    python scripts/code_batch.py submit  track1 --reviewer gemini
    python scripts/code_batch.py status  track1 --reviewer gemini
    python scripts/code_batch.py download track1 --reviewer gemini

    python scripts/code_batch.py prepare track2 --reviewer gemini
    python scripts/code_batch.py submit  track2 --reviewer gemini
    python scripts/code_batch.py status  track2 --reviewer gemini
    python scripts/code_batch.py download track2 --reviewer gemini

Output files include the reviewer name:
    track1_coded_gpt.jsonl / track1_coded_gemini.jsonl
    track1_flagship_coded_gpt.jsonl / track1_flagship_coded_gemini.jsonl
    track2_coded_gpt.csv / track2_coded_gemini.csv
"""

import argparse
import csv
import json
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
load_dotenv(Path(__file__).parent.parent.parent / ".env")

DATA_DIR = Path(__file__).parent.parent / "data"

# ─────────────────────────────────────────────────────────────────────────────
# Reviewer configs
# ─────────────────────────────────────────────────────────────────────────────

REVIEWERS = {
    "gpt": {
        "model": "gpt-5.2",
        "label": "GPT-5.2",
        "input_per_mtok_batch": 1.00,   # $2.00 * 50%
        "output_per_mtok_batch": 4.00,  # $8.00 * 50%
    },
    "gemini": {
        "model": "models/gemini-3.1-pro-preview",
        "label": "Gemini 3.1 Pro",
        "input_per_mtok_batch": 1.00,   # $2.00 * 50%
        "output_per_mtok_batch": 6.00,  # $12.00 * 50%
    },
}

FRAMING_LABELS = {"f1": "Generic", "f2": "Specific", "f3": "Direct"}
CITATION_LABELS = {"c0": "Unprompted", "c1": "Cite sources"}


# ─────────────────────────────────────────────────────────────────────────────
# Coding prompts (shared across reviewers)
# ─────────────────────────────────────────────────────────────────────────────

TRACK1_SYSTEM_PROMPT = """You are coding AI agent responses for a research study on how AI agents cite Canadian news sources. You must be precise and consistent.

Given:
- The PROMPT that was asked (a natural consumer question about a Canadian news event)
- The AI agent's RESPONSE
- GROUND TRUTH: which Canadian news outlets actually covered this story, and the original headline

Produce a JSON object with exactly these fields:

{
  "knowledge_level": "knowledgeable" | "partial" | "no_knowledge" | "refusal",
  "sources_cited": ["list of every news outlet or media org mentioned by name"],
  "citation_type": "named_as_source" | "recommended" | "vague_reference" | "none",
  "canadian_sources_cited": <int>,
  "non_canadian_sources_cited": <int>,
  "accuracy": "accurate" | "mostly_accurate" | "inaccurate" | "unverifiable"
}

DEFINITIONS:

knowledge_level:
- "knowledgeable": Clearly knows what happened — provides specific, correct details about the event
- "partial": Has some relevant information but hedges significantly, mixes correct and incorrect info, or is vague
- "no_knowledge": Clearly doesn't know — gives generic filler, says it doesn't have information, or is entirely wrong
- "refusal": Explicitly declines to answer

citation_type (the DOMINANT pattern — pick the strongest one present):
- "named_as_source": Uses outlet as an information source — "According to CBC...", "CBC reported that...", "as reported by the Globe and Mail"
- "recommended": Suggests outlets to check but doesn't use them as sources — "Check CBC or Globe and Mail for details", "I'd recommend looking at..."
- "vague_reference": Generic attribution — "Canadian media reported...", "according to reports...", "news sources indicate..."
- "none": No source attribution of any kind

sources_cited: List ALL news outlets/media orgs mentioned BY NAME in the response, regardless of how they're referenced. Include both Canadian and non-Canadian. Use canonical names (e.g., "CBC News" not "the CBC's website").

accuracy: Compare the response's factual claims against the original headline and general knowledge of the event.
- "accurate": Key facts correct, no significant errors
- "mostly_accurate": Broadly correct but minor errors or imprecise details
- "inaccurate": Significant factual errors
- "unverifiable": Not enough detail to assess, or agent didn't really answer

Output ONLY the JSON object. No explanation, no markdown fences."""


TRACK2_SYSTEM_PROMPT = """You are coding AI agent responses for a research study on how AI agents reproduce and attribute Canadian journalism. Be precise and consistent.

Given:
- The SOURCE ARTICLE headline, outlet, and key distinctive facts
- The PROBE PROMPT that was sent to the AI agent
- The AI agent's RESPONSE

Produce a JSON object with exactly these fields:

{
  "reproduction_level": "verbatim" | "close_paraphrase" | "partial" | "topic_only" | "none",
  "attribution_level": "full" | "outlet_named" | "vague" | "none" | "misattribution",
  "link_quality": "working" | "broken" | "hallucinated" | "none",
  "factual_accuracy": "accurate" | "mostly_accurate" | "inaccurate" | "unverifiable",
  "paywalled_content_reproduced": true | false,
  "sources_mentioned": ["list of all news outlets mentioned by name"],
  "canadian_sources_count": <int>,
  "non_canadian_sources_count": <int>
}

DEFINITIONS:

reproduction_level:
- "verbatim": Response contains phrases of 5+ words that appear word-for-word in the source article
- "close_paraphrase": Response closely follows the structure and unique details of the article, rephrasing but clearly derived from it
- "partial": Response includes some distinctive facts from the article mixed with general knowledge
- "topic_only": Response discusses the general topic but shows no evidence of having accessed this specific article
- "none": Response doesn't address the article's content

attribution_level:
- "full": Names the outlet AND provides a link or specific article reference
- "outlet_named": Names the outlet as a source but no link (e.g., "According to the Toronto Star...")
- "vague": Generic attribution ("media reports suggest...", "according to reports...")
- "none": No attribution despite reproducing content
- "misattribution": Attributes content to the wrong outlet

link_quality:
- "working": Provides a URL that appears to be a real, correct link to the source
- "broken": Provides a URL that appears malformed or incorrect
- "hallucinated": Provides a URL that looks plausible but is fabricated
- "none": No links provided

paywalled_content_reproduced: true if the response reproduces distinctive details that are only available behind a paywall (the article's source outlet uses a paywall)

Output ONLY the JSON object. No explanation, no markdown fences."""


# ─────────────────────────────────────────────────────────────────────────────
# Path helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_paths(track: str, reviewer: str, tier: str = "economy", lang: str = "en"):
    flag = "_flagship" if tier == "flagship" else ""
    lang_s = f"_{lang}" if lang != "en" else ""
    prefix = f"{reviewer}_coding_{track}{flag}{lang_s}"
    if track == "track1":
        coded = DATA_DIR / f"track1{flag}_coded_{reviewer}{lang_s}.jsonl"
    else:
        coded = DATA_DIR / f"track2_coded_{reviewer}.csv"
    return {
        "batch_input": DATA_DIR / f"{prefix}_input.jsonl",
        "batch_output": DATA_DIR / f"{prefix}_output.jsonl",
        "coded": coded,
        "batch_id": DATA_DIR / f".{prefix}_batch_id",  # OpenAI batch ID
        "batch_name": DATA_DIR / f".{prefix}_batch_name",  # Gemini job name
    }


# ─────────────────────────────────────────────────────────────────────────────
# Prepare: build batch JSONL (format depends on reviewer)
# ─────────────────────────────────────────────────────────────────────────────

def _build_track1_messages(tier: str, lang: str = "en"):
    """Load Track 1 responses and build (custom_id, system_prompt, user_msg) tuples."""
    flag = "_flagship" if tier == "flagship" else ""
    lang_s = f"_{lang}" if lang != "en" else ""
    responses_path = DATA_DIR / f"track1{flag}_responses{lang_s}.jsonl"
    prompts_path = DATA_DIR / f"track1_prompts{lang_s}.jsonl"

    gt = {}
    with open(prompts_path) as f:
        for line in f:
            r = json.loads(line)
            gt[r["story_id"]] = r

    all_responses = {}
    with open(responses_path) as f:
        for line in f:
            r = json.loads(line)
            if r.get("response") and not r.get("error"):
                key = (r["story_id"], r["provider"])
                all_responses[key] = r

    responses = list(all_responses.values())
    print(f"Loaded {len(responses)} valid {tier} responses")
    return responses, gt


def _build_track2_messages():
    """Load Track 2 responses and build message data."""
    articles_path = DATA_DIR / "track2_articles.jsonl"
    responses_path = DATA_DIR / "track2_responses.jsonl"
    db_path = DATA_DIR / "lexis_articles.db"

    articles = {}
    with open(articles_path) as f:
        for line in f:
            line = line.strip()
            if line:
                a = json.loads(line)
                articles[a["id"]] = a

    responses = []
    with open(responses_path) as f:
        for line in f:
            line = line.strip()
            if line:
                responses.append(json.loads(line))

    bodies = {}
    if db_path.exists():
        conn = sqlite3.connect(db_path)
        for aid, a in articles.items():
            db_id = a.get("lexis_db_id")
            if db_id:
                row = conn.execute("SELECT body FROM articles WHERE id = ?", (db_id,)).fetchone()
                if row:
                    bodies[aid] = row[0]
        conn.close()

    return responses, articles, bodies


def _load_coded_track1(paths):
    coded_ids = set()
    if paths["coded"].exists():
        with open(paths["coded"]) as f:
            for line in f:
                try:
                    c = json.loads(line)
                    coded_ids.add((c["story_id"], c["provider"]))
                except Exception:
                    pass
    return coded_ids


def _load_coded_track2(paths):
    coded_keys = set()
    if paths["coded"].exists():
        with open(paths["coded"]) as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("llm_reproduction"):
                    coded_keys.add((row["article_id"], row["agent"], row["framing"], row["citation"]))
    return coded_keys


def prepare_track1(reviewer: str, tier: str, lang: str, paths: dict, limit: int = None):
    responses, gt = _build_track1_messages(tier, lang)
    coded_ids = _load_coded_track1(paths)
    if coded_ids:
        responses = [r for r in responses if (r["story_id"], r["provider"]) not in coded_ids]
        print(f"After skipping already coded: {len(responses)} remaining")

    if limit:
        responses = responses[:limit]
        print(f"Limiting to {limit} responses")

    cfg = REVIEWERS[reviewer]
    n = 0
    with open(paths["batch_input"], "w") as f:
        for r in responses:
            story_gt = gt.get(r["story_id"], {})
            outlets = story_gt.get("outlets", "")
            if isinstance(outlets, list):
                outlets = ", ".join(outlets[:15])
            headline = story_gt.get("original_headline", "N/A")

            user_msg = (
                f"PROMPT: {r['prompt']}\n\n"
                f"RESPONSE ({r['provider']} / {r['model']}):\n"
                f"{r['response']}\n\n"
                f"GROUND TRUTH OUTLETS: {outlets}\n"
                f"ORIGINAL HEADLINE: {headline}"
            )
            custom_id = f"{r['story_id']}_{r['provider']}"

            if reviewer == "gpt":
                req = _openai_request(custom_id, TRACK1_SYSTEM_PROMPT, user_msg, max_tokens=500)
            else:
                req = _gemini_request(custom_id, TRACK1_SYSTEM_PROMPT, user_msg, max_tokens=500)
            f.write(json.dumps(req) + "\n")
            n += 1

    print(f"Wrote {n} requests to {paths['batch_input']}")
    _estimate_cost(n, 500, 150, cfg)


def prepare_track2(reviewer: str, paths: dict):
    responses, articles, bodies = _build_track2_messages()
    coded_keys = _load_coded_track2(paths)

    cfg = REVIEWERS[reviewer]
    n = 0
    seen = set()
    with open(paths["batch_input"], "w") as f:
        for r in responses:
            aid = r["article_id"]
            key = (aid, r["agent"], r["framing"], r["citation"])
            if key in coded_keys or key in seen:
                continue
            seen.add(key)

            article = articles.get(aid, {})
            body = bodies.get(aid, "")
            facts_str = "\n".join(f"- {fact}" for fact in article.get("distinctive_facts", []))
            body_text = body or ""

            user_msg = (
                f"SOURCE ARTICLE:\n"
                f"Outlet: {article.get('source', 'Unknown')}\n"
                f"Headline: {article.get('headline', 'Unknown')}\n"
                f"Date: {article.get('date', 'Unknown')}\n"
                f"Paywall: {'Yes' if article.get('paywall') else 'No'}\n"
                f"Distinctive facts:\n{facts_str}\n\n"
                f"FULL ARTICLE TEXT:\n{body_text}\n\n"
                f"---\n\n"
                f"PROBE PROMPT ({FRAMING_LABELS.get(r['framing'], r['framing'])}, "
                f"{CITATION_LABELS.get(r['citation'], r['citation'])}):\n"
                f"{r['prompt']}\n\n"
                f"AI AGENT RESPONSE ({r.get('agent_label', r['agent'])}):\n"
                f"{r['response']}"
            )
            custom_id = f"{aid}__{r['agent']}__{r['framing']}__{r['citation']}"

            if reviewer == "gpt":
                req = _openai_request(custom_id, TRACK2_SYSTEM_PROMPT, user_msg, max_tokens=4096)
            else:
                req = _gemini_request(custom_id, TRACK2_SYSTEM_PROMPT, user_msg, max_tokens=4096)
            f.write(json.dumps(req) + "\n")
            n += 1

    print(f"Wrote {n} requests to {paths['batch_input']}")
    _estimate_cost(n, 1500, 200, cfg)


# ─────────────────────────────────────────────────────────────────────────────
# Request format builders
# ─────────────────────────────────────────────────────────────────────────────

def _openai_request(custom_id: str, system: str, user: str, max_tokens: int) -> dict:
    req = {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/responses",
        "body": {
            "model": REVIEWERS["gpt"]["model"],
            "input": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_output_tokens": max_tokens,
            "reasoning": {"effort": "low"},
        },
    }
    return req


def _gemini_request(custom_id: str, system: str, user: str, max_tokens: int) -> dict:
    return {
        "key": custom_id,
        "request": {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": user}], "role": "user"}],
            "generation_config": {"max_output_tokens": max_tokens},
        },
    }


def _estimate_cost(n, avg_input, avg_output, cfg):
    cost = n * (avg_input * cfg["input_per_mtok_batch"] / 1e6
                + avg_output * cfg["output_per_mtok_batch"] / 1e6)
    print(f"Estimated batch cost ({cfg['label']}, 50% discount): ~${cost:.2f}")


# ─────────────────────────────────────────────────────────────────────────────
# Submit
# ─────────────────────────────────────────────────────────────────────────────

def submit_gpt(paths: dict):
    from openai import OpenAI
    client = OpenAI()

    print(f"Uploading {paths['batch_input']}...")
    with open(paths["batch_input"], "rb") as f:
        upload = client.files.create(file=f, purpose="batch")
    print(f"Uploaded: {upload.id}")

    batch = client.batches.create(
        input_file_id=upload.id,
        endpoint="/v1/responses",
        completion_window="24h",
    )
    print(f"Batch submitted: {batch.id}")
    print(f"Status: {batch.status}")
    paths["batch_id"].write_text(batch.id)


def submit_gemini(paths: dict):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    print(f"Uploading {paths['batch_input']}...")
    uploaded_file = client.files.upload(
        file=str(paths["batch_input"]),
        config=types.UploadFileConfig(
            display_name=paths["batch_input"].stem,
            mime_type="jsonl",
        ),
    )
    print(f"Uploaded: {uploaded_file.name}")

    batch_job = client.batches.create(
        model=REVIEWERS["gemini"]["model"],
        src=uploaded_file.name,
        config={"display_name": paths["batch_input"].stem},
    )
    print(f"Batch submitted: {batch_job.name}")
    print(f"State: {batch_job.state}")
    paths["batch_name"].write_text(batch_job.name)


# ─────────────────────────────────────────────────────────────────────────────
# Status
# ─────────────────────────────────────────────────────────────────────────────

def status_gpt(paths: dict):
    from openai import OpenAI
    client = OpenAI()
    batch_id = paths["batch_id"].read_text().strip()
    batch = client.batches.retrieve(batch_id)
    print(f"Batch: {batch.id}")
    print(f"Status: {batch.status}")
    if batch.request_counts:
        rc = batch.request_counts
        print(f"Completed: {rc.completed}/{rc.total} ({rc.failed} failed)")


def status_gemini(paths: dict):
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    job_name = paths["batch_name"].read_text().strip()
    batch_job = client.batches.get(name=job_name)
    print(f"Job: {batch_job.name}")
    print(f"State: {batch_job.state}")


# ─────────────────────────────────────────────────────────────────────────────
# Download + parse
# ─────────────────────────────────────────────────────────────────────────────

def _clean_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    text = re.sub(r",\s*}", "}", text)
    text = re.sub(r",\s*]", "]", text)
    if text.count("{") > text.count("}"):
        text = text.rstrip().rstrip(",")
        text += "}" * (text.count("{") - text.count("}"))
    return text


def _extract_text_gpt(body):
    for item in body["output"]:
        if item.get("type") == "message" and item.get("content"):
            for c in item["content"]:
                if c.get("type") == "output_text":
                    return c["text"].strip()
    raise ValueError("No output_text found in response")


def _extract_text_gemini(result):
    return result["response"]["candidates"][0]["content"]["parts"][0]["text"].strip()


def download_track1(reviewer: str, paths: dict):
    results = _download_raw(reviewer, paths)
    if results is None:
        return

    coded = 0
    parse_errors = 0
    api_errors = 0
    existing_ids = _load_coded_track1(paths)

    with open(paths["coded"], "a") as f_out:
        for custom_id, result in results:
            parts = custom_id.rsplit("_", 1)
            story_id = parts[0]
            provider = parts[1] if len(parts) > 1 else "unknown"

            if (story_id, provider) in existing_ids:
                continue

            try:
                if reviewer == "gpt":
                    text = _extract_text_gpt(result["response"]["body"])
                else:
                    text = _extract_text_gemini(result)
                text = _clean_json(text)
                coding = json.loads(text)

                record = {
                    "story_id": story_id,
                    "provider": provider,
                    **coding,
                    "coded_by": REVIEWERS[reviewer]["label"],
                    "coded_at": datetime.now().isoformat(),
                }
                f_out.write(json.dumps(record, ensure_ascii=False) + "\n")
                coded += 1
            except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
                parse_errors += 1
                if parse_errors <= 10:
                    print(f"  Parse error on {custom_id}: {e}")

    print(f"\nCoded: {coded} | Parse errors: {parse_errors} | API errors: {api_errors}")
    print(f"Output: {paths['coded']}")


def download_track2(reviewer: str, paths: dict):
    results = _download_raw(reviewer, paths)
    if results is None:
        return

    coded_rows = []
    parse_errors = 0

    for custom_id, result in results:
        parts = custom_id.split("__")
        if len(parts) != 4:
            parse_errors += 1
            continue
        article_id, agent, framing, citation = parts

        try:
            if reviewer == "gpt":
                text = _extract_text_gpt(result["response"]["body"])
            else:
                text = _extract_text_gemini(result)
            text = _clean_json(text)
            coding = json.loads(text)

            coded_rows.append({
                "article_id": article_id,
                "agent": agent,
                "framing": framing,
                "citation": citation,
                "llm_reproduction": coding.get("reproduction_level", ""),
                "llm_attribution": coding.get("attribution_level", ""),
                "llm_link_quality": coding.get("link_quality", ""),
                "llm_accuracy": coding.get("factual_accuracy", ""),
                "llm_paywall_reproduced": coding.get("paywalled_content_reproduced", ""),
                "llm_sources_mentioned": "|".join(coding.get("sources_mentioned", [])),
                "llm_canadian_sources": coding.get("canadian_sources_count", 0),
                "llm_non_canadian_sources": coding.get("non_canadian_sources_count", 0),
                "coded_by": REVIEWERS[reviewer]["label"],
            })
        except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
            parse_errors += 1
            if parse_errors <= 10:
                print(f"  Parse error on {custom_id}: {e}")

    if coded_rows:
        fieldnames = list(coded_rows[0].keys())
        with open(paths["coded"], "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(coded_rows)

    print(f"\nCoded: {len(coded_rows)} | Parse errors: {parse_errors}")
    print(f"Output: {paths['coded']}")


def _download_raw(reviewer: str, paths: dict):
    """Download raw batch output. Returns list of (custom_id, result) tuples, or None."""
    if reviewer == "gpt":
        return _download_raw_gpt(paths)
    else:
        return _download_raw_gemini(paths)


def _download_raw_gpt(paths: dict):
    from openai import OpenAI
    client = OpenAI()
    batch_id = paths["batch_id"].read_text().strip()
    batch = client.batches.retrieve(batch_id)

    if batch.status != "completed":
        print(f"Batch not done. Status: {batch.status}")
        if batch.request_counts:
            rc = batch.request_counts
            print(f"Progress: {rc.completed}/{rc.total} ({rc.failed} failed)")
        return None

    print(f"Downloading output file {batch.output_file_id}...")
    content = client.files.content(batch.output_file_id)
    paths["batch_output"].write_bytes(content.read())
    print(f"Saved to {paths['batch_output']}")

    results = []
    with open(paths["batch_output"]) as f:
        for line in f:
            r = json.loads(line)
            if r.get("error"):
                continue
            results.append((r["custom_id"], r))
    return results


def _download_raw_gemini(paths: dict):
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    job_name = paths["batch_name"].read_text().strip()
    batch_job = client.batches.get(name=job_name)

    if batch_job.state.name != "JOB_STATE_SUCCEEDED":
        print(f"Job not done. State: {batch_job.state}")
        return None

    result_file = batch_job.dest.file_name
    print(f"Downloading results from {result_file}...")
    content = client.files.download(file=result_file)
    raw = content if isinstance(content, bytes) else content.encode("utf-8")
    paths["batch_output"].write_bytes(raw)
    print(f"Saved to {paths['batch_output']}")

    results = []
    with open(paths["batch_output"]) as f:
        for line in f:
            r = json.loads(line)
            if r.get("error") or not r.get("response"):
                continue
            results.append((r.get("key", ""), r))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Batch-code responses via OpenAI or Gemini")
    parser.add_argument("command", choices=["prepare", "submit", "status", "download"])
    parser.add_argument("track", choices=["track1", "track2"])
    parser.add_argument("--reviewer", choices=["gpt", "gemini"], required=True)
    parser.add_argument("--tier", choices=["economy", "flagship"], default="economy",
                        help="Track 1 model tier (default: economy)")
    parser.add_argument("--lang", choices=["en", "fr"], default="en",
                        help="Story language (default: en)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit prepare to N responses (for testing)")
    args = parser.parse_args()

    paths = get_paths(args.track, args.reviewer, args.tier, args.lang)

    if args.command == "prepare":
        if args.track == "track1":
            prepare_track1(args.reviewer, args.tier, args.lang, paths, limit=args.limit)
        else:
            prepare_track2(args.reviewer, paths)

    elif args.command == "submit":
        if args.reviewer == "gpt":
            submit_gpt(paths)
        else:
            submit_gemini(paths)

    elif args.command == "status":
        if args.reviewer == "gpt":
            status_gpt(paths)
        else:
            status_gemini(paths)

    elif args.command == "download":
        if args.track == "track1":
            download_track1(args.reviewer, paths)
        else:
            download_track2(args.reviewer, paths)


if __name__ == "__main__":
    main()
