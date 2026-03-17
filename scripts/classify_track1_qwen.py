#!/usr/bin/env python3
"""
Classify Track 1 responses using a local vLLM server (Qwen3.5-35B-A3B-FP8).

Processes all four corpora: economy/flagship × EN/FR.

Reads:  data/track1_{flagship_}responses{_fr}.jsonl
        data/track1_prompts{_fr}.jsonl  (ground truth)
Writes: data/track1_coded_qwen{_flagship}{_fr}.jsonl

Usage:
    python classify_track1_qwen.py --port 8192
"""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openai import OpenAI

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"

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


def clean_json(text):
    import re
    text = text.strip()
    # Strip <think>...</think> blocks
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # Strip markdown fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    text = re.sub(r",\s*}", "}", text)
    text = re.sub(r",\s*]", "]", text)
    if text.count("{") > text.count("}"):
        text = text.rstrip().rstrip(",")
        text += "}" * (text.count("{") - text.count("}"))
    return text


def classify_one(client, model, r, gt_entry, max_retries=3):
    user_msg = (
        f"GROUND TRUTH:\n"
        f"Headline: {gt_entry.get('original_headline', 'Unknown')}\n"
        f"Canadian outlets that covered this story: {gt_entry.get('outlets', 'Unknown')}\n\n"
        f"PROMPT:\n{r['prompt']}\n\n"
        f"AI AGENT RESPONSE ({r['provider']}):\n{r['response']}"
    )
    key = (r["story_id"], r["provider"])

    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": CODING_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=256,
                temperature=0.0,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
            text = resp.choices[0].message.content.strip()
            text = clean_json(text)
            coding = json.loads(text)
            return {"story_id": r["story_id"], "provider": r["provider"],
                    "coding": coding, "error": None}
        except json.JSONDecodeError as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return {"story_id": r["story_id"], "provider": r["provider"],
                    "coding": None, "error": f"JSONDecodeError: {e}"}
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return {"story_id": r["story_id"], "provider": r["provider"],
                    "coding": None, "error": str(e)}


def process_corpus(client, model, responses_path, prompts_path, output_path, workers):
    gt = load_ground_truth(prompts_path)

    # Deduplicate: latest successful response per story+provider
    all_responses = {}
    with open(responses_path) as f:
        for line in f:
            r = json.loads(line)
            if r.get("response") and not r.get("error"):
                all_responses[(r["story_id"], r["provider"])] = r
    responses = list(all_responses.values())
    print(f"  {responses_path.name}: {len(responses)} valid responses", flush=True)

    # Resume
    done_keys = set()
    if output_path.exists():
        with open(output_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    row = json.loads(line)
                    done_keys.add((row["story_id"], row["provider"]))
        if done_keys:
            print(f"  Resuming: {len(done_keys)} done, {len(responses)-len(done_keys)} remaining", flush=True)

    todo = [r for r in responses if (r["story_id"], r["provider"]) not in done_keys]
    if not todo:
        print(f"  Already complete.", flush=True)
        return

    n_done = n_errors = 0
    t0 = time.time()

    with open(output_path, "a") as fout:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(classify_one, client, model, r, gt.get(r["story_id"], {})): r
                for r in todo
            }
            for future in as_completed(futures):
                result = future.result()
                fout.write(json.dumps(result) + "\n")
                fout.flush()
                n_done += 1
                if result["error"]:
                    n_errors += 1
                if n_done % 200 == 0 or n_done == len(todo):
                    elapsed = time.time() - t0
                    rate = n_done / elapsed
                    eta = (len(todo) - n_done) / rate if rate > 0 else 0
                    print(f"  {n_done}/{len(todo)} ({100*n_done/len(todo):.0f}%) "
                          f"— {rate:.1f} req/s — ETA {eta/60:.0f}m — errors: {n_errors}",
                          flush=True)

    print(f"  Done: {n_done} coded, {n_errors} errors → {output_path.name}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8192)
    parser.add_argument("--model", default="Qwen/Qwen3.5-35B-A3B-FP8")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--suffix", default="qwen",
                        help="Output file suffix, e.g. 'qwen' → track1_coded_qwen.jsonl, 'qwen27' → track1_coded_qwen27.jsonl")
    args = parser.parse_args()

    client = OpenAI(base_url=f"http://localhost:{args.port}/v1", api_key="not-needed")
    s = args.suffix

    corpora = [
        ("economy EN",   "track1_responses.jsonl",             "track1_prompts.jsonl",    f"track1_coded_{s}.jsonl"),
        ("economy FR",   "track1_responses_fr.jsonl",          "track1_prompts_fr.jsonl", f"track1_coded_{s}_fr.jsonl"),
        ("flagship EN",  "track1_flagship_responses.jsonl",    "track1_prompts.jsonl",    f"track1_flagship_coded_{s}.jsonl"),
        ("flagship FR",  "track1_flagship_responses_fr.jsonl", "track1_prompts_fr.jsonl", f"track1_flagship_coded_{s}_fr.jsonl"),
    ]

    for label, resp_file, prompts_file, out_file in corpora:
        print(f"\n=== {label} ===", flush=True)
        process_corpus(
            client, args.model,
            DATA_DIR / resp_file,
            DATA_DIR / prompts_file,
            DATA_DIR / out_file,
            args.workers,
        )

    print("\nAll corpora complete.", flush=True)


if __name__ == "__main__":
    main()
