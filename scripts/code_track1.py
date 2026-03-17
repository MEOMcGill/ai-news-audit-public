"""
Code Track 1 responses using OpenAI Batch API.

Usage:
    python scripts/code_track1.py prepare                          # economy, English
    python scripts/code_track1.py prepare --model flagship         # flagship, English
    python scripts/code_track1.py prepare --lang fr                # economy, French
    python scripts/code_track1.py prepare --model flagship --lang fr
    python scripts/code_track1.py submit
    python scripts/code_track1.py status
    python scripts/code_track1.py download

File naming:
    economy / en  → track1_responses.jsonl          → track1_coded.jsonl
    flagship / en → track1_flagship_responses.jsonl → track1_flagship_coded.jsonl
    economy / fr  → track1_responses_fr.jsonl       → track1_coded_fr.jsonl
    flagship / fr → track1_flagship_responses_fr.jsonl → track1_flagship_coded_fr.jsonl
"""

import argparse
import json
import re
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from openai import OpenAI

DATA_DIR = Path(__file__).parent.parent / "data"

# Economy-tier and flagship model names
CODING_MODELS = {
    "economy":  "gpt-5-mini",
    "flagship": "gpt-5.2",
}


def get_paths(model_tier: str, lang: str):
    """Return all data file paths for a given model tier and language."""
    flag = "_flagship" if model_tier == "flagship" else ""
    lang_s = f"_{lang}" if lang != "en" else ""
    return {
        "responses":    DATA_DIR / f"track1{flag}_responses{lang_s}.jsonl",
        "prompts":      DATA_DIR / f"track1_prompts{lang_s}.jsonl",
        "batch_input":  DATA_DIR / f"track1{flag}_coding_batch_input{lang_s}.jsonl",
        "batch_output": DATA_DIR / f"track1{flag}_coding_batch_output{lang_s}.jsonl",
        "coded":        DATA_DIR / f"track1{flag}_coded{lang_s}.jsonl",
        "batch_id":     DATA_DIR / f".track1{flag}_batch_id{lang_s}",
    }


CODING_SYSTEM_PROMPT = """You are coding AI agent responses for a research study on how AI agents cite Canadian news sources. You must be precise and consistent.

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


def load_ground_truth(prompts_path):
    gt = {}
    with open(prompts_path) as f:
        for line in f:
            r = json.loads(line)
            gt[r["story_id"]] = r
    return gt


def prepare(model_name: str, model_tier: str, paths: dict):
    """Generate batch input JSONL."""
    gt = load_ground_truth(paths["prompts"])

    # Deduplicate: keep latest successful response per story+provider
    all_responses = {}
    with open(paths["responses"]) as f:
        for line in f:
            r = json.loads(line)
            if r.get("response") and not r.get("error"):
                key = (r["story_id"], r["provider"])
                all_responses[key] = r

    responses = list(all_responses.values())
    print(f"Loaded {len(responses)} valid responses to code (deduplicated)")

    # Skip already-coded responses
    coded_ids = set()
    if paths["coded"].exists():
        with open(paths["coded"]) as f:
            for line in f:
                try:
                    c = json.loads(line)
                    coded_ids.add((c["story_id"], c["provider"]))
                except Exception:
                    pass
    if coded_ids:
        responses = [r for r in responses if (r["story_id"], r["provider"]) not in coded_ids]
        print(f"After skipping already coded: {len(responses)} remaining")

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

            batch_request = {
                "custom_id": f"{r['story_id']}_{r['provider']}",
                "method": "POST",
                "url": "/v1/responses",
                "body": {
                    "model": model_name,
                    "input": [
                        {"role": "system", "content": CODING_SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    "max_output_tokens": 500,
                },
            }
            # Add reasoning for models that support it
            if model_tier == "flagship" or "mini" in model_name:
                batch_request["body"]["reasoning"] = {"effort": "low"}

            f.write(json.dumps(batch_request) + "\n")

    print(f"Wrote {len(responses)} requests to {paths['batch_input']}")

    # Cost estimate (batch API = 50% discount)
    avg_input, avg_output = 500, 150
    if "mini" in model_name:
        cost = len(responses) * (avg_input * 0.25 / 1e6 + avg_output * 2.00 / 1e6) * 0.5
    else:
        cost = len(responses) * (avg_input * 2.00 / 1e6 + avg_output * 8.00 / 1e6) * 0.5
    print(f"Estimated batch cost ({model_name}, 50% discount): ~${cost:.2f}")


def submit(paths: dict):
    """Upload batch input and submit the batch job."""
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
    print(f"Batch ID saved to {paths['batch_id']}")


def status(paths: dict):
    """Check batch status."""
    client = OpenAI()
    batch_id = paths["batch_id"].read_text().strip()
    batch = client.batches.retrieve(batch_id)

    print(f"Batch: {batch.id}")
    print(f"Status: {batch.status}")
    print(f"Created: {datetime.fromtimestamp(batch.created_at).strftime('%H:%M:%S')}")
    if batch.request_counts:
        rc = batch.request_counts
        print(f"Completed: {rc.completed}/{rc.total} ({rc.failed} failed)")
    if batch.output_file_id:
        print(f"Output file: {batch.output_file_id}")
    if batch.error_file_id:
        print(f"Error file: {batch.error_file_id}")


def _extract_text(body):
    """Extract output text from a batch response body (standard and reasoning formats)."""
    for item in body["output"]:
        if item.get("type") == "message" and item.get("content"):
            for c in item["content"]:
                if c.get("type") == "output_text":
                    return c["text"].strip()
    raise ValueError("No output_text found in response")


def _clean_json(text):
    """Strip markdown fences, fix trailing commas, patch truncated JSON."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    text = re.sub(r",\s*}", "}", text)
    text = re.sub(r",\s*]", "]", text)
    if text.count("{") > text.count("}"):
        text = text.rstrip().rstrip(",")
        text += "}" * (text.count("{") - text.count("}"))
    return text


def download(paths: dict):
    """Download batch results and parse into coded JSONL."""
    client = OpenAI()
    batch_id = paths["batch_id"].read_text().strip()
    batch = client.batches.retrieve(batch_id)

    if batch.status != "completed":
        print(f"Batch not done yet. Status: {batch.status}")
        if batch.request_counts:
            rc = batch.request_counts
            print(f"Progress: {rc.completed}/{rc.total} ({rc.failed} failed)")
        return

    print(f"Downloading output file {batch.output_file_id}...")
    content = client.files.content(batch.output_file_id)
    paths["batch_output"].write_bytes(content.read())
    print(f"Saved raw output to {paths['batch_output']}")

    coded = 0
    parse_errors = 0
    api_errors = 0
    existing_ids = set()
    if paths["coded"].exists():
        with open(paths["coded"]) as f:
            for line in f:
                try:
                    c = json.loads(line)
                    existing_ids.add((c["story_id"], c["provider"]))
                except Exception:
                    pass

    with open(paths["batch_output"]) as f_in, open(paths["coded"], "a") as f_out:
        for line in f_in:
            result = json.loads(line)
            custom_id = result["custom_id"]

            # custom_id format: "2024-01-01_rank1_openai"
            parts = custom_id.rsplit("_", 1)
            story_id = parts[0]
            provider = parts[1] if len(parts) > 1 else "unknown"

            if (story_id, provider) in existing_ids:
                continue
            if result.get("error"):
                api_errors += 1
                continue

            try:
                body = result["response"]["body"]
                text = _extract_text(body)
                text = _clean_json(text)
                coding = json.loads(text)

                record = {
                    "story_id": story_id,
                    "provider": provider,
                    **coding,
                    "coded_at": datetime.now().isoformat(),
                }
                f_out.write(json.dumps(record, ensure_ascii=False) + "\n")
                coded += 1

            except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
                parse_errors += 1
                if parse_errors <= 10:
                    print(f"  Parse error on {custom_id}: {e}")

    print(f"\nCoded: {coded} responses")
    print(f"Parse errors: {parse_errors}")
    print(f"API errors: {api_errors}")
    print(f"Output: {paths['coded']}")


def main():
    parser = argparse.ArgumentParser(description="Code Track 1 responses via OpenAI Batch API")
    parser.add_argument("command", choices=["prepare", "submit", "status", "download"],
                        help="Action to perform")
    parser.add_argument("--model", choices=["economy", "flagship"], default="economy",
                        help="Model tier: economy (gpt-5-mini) or flagship (gpt-5.2) (default: economy)")
    parser.add_argument("--lang", choices=["en", "fr"], default="en",
                        help="Story language: en or fr (default: en)")
    args = parser.parse_args()

    model_name = CODING_MODELS[args.model]
    paths = get_paths(model_tier=args.model, lang=args.lang)

    print(f"Model tier: {args.model} ({model_name})")
    print(f"Language:   {args.lang}")
    print(f"Responses:  {paths['responses']}")
    print(f"Coded:      {paths['coded']}")

    if args.command == "prepare":
        prepare(model_name, args.model, paths)
    elif args.command == "submit":
        submit(paths)
    elif args.command == "status":
        status(paths)
    elif args.command == "download":
        download(paths)


if __name__ == "__main__":
    main()
