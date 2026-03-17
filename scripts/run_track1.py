"""
Track 1: Citation Audit — Training Data Attribution

For each of the top Canadian news stories (Jan 2024 – Feb 2026),
ask all 4 AI agents about the event WITHOUT web search. Tests whether
models internalized Canadian journalism and whether they attribute it.

Usage:
    python scripts/run_track1.py                              # economy, English
    python scripts/run_track1.py --model flagship             # flagship, English
    python scripts/run_track1.py --lang fr                    # economy, French
    python scripts/run_track1.py --model flagship --lang fr   # flagship, French
    python scripts/run_track1.py --test 3                     # test with 3 stories
    python scripts/run_track1.py -p openai gemini             # subset of providers
    python scripts/run_track1.py --dry-run                    # cost estimate only
    python scripts/run_track1.py --workers 8                  # control parallelism

File naming:
    economy / en  → track1_responses.jsonl
    flagship / en → track1_flagship_responses.jsonl
    economy / fr  → track1_responses_fr.jsonl
    flagship / fr → track1_flagship_responses_fr.jsonl
"""

import argparse
import json
import sys
import time
import threading
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent))

DATA_DIR = Path(__file__).parent.parent / "data"

SYSTEM_PROMPTS = {
    "en": "You are a helpful assistant. Answer the user's question about Canadian news. Be concise.",
    "fr": "Tu es un assistant utile. Réponds à la question de l'utilisateur sur l'actualité canadienne. Sois concis.",
}

MAX_TOKENS = 500
write_lock = threading.Lock()


def get_paths(model_tier: str, lang: str):
    flag = "_flagship" if model_tier == "flagship" else ""
    lang_s = f"_{lang}" if lang != "en" else ""
    return {
        "prompts": DATA_DIR / f"track1_prompts{lang_s}.jsonl",
        "output":  DATA_DIR / f"track1{flag}_responses{lang_s}.jsonl",
    }


def load_prompts(path, limit=None):
    prompts = []
    with open(path) as f:
        for line in f:
            prompts.append(json.loads(line))
            if limit and len(prompts) >= limit:
                break
    return prompts


def load_completed(path):
    completed = set()
    if path.exists():
        with open(path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    completed.add((r["story_id"], r["provider"]))
                except Exception:
                    pass
    return completed


def query_provider(provider: str, prompt: str, sid: str, MODELS, query_one, system_prompt: str) -> dict:
    t0 = time.time()
    try:
        response = query_one(provider, prompt, system=system_prompt, max_tokens=MAX_TOKENS)
        elapsed = time.time() - t0
        return {
            "story_id": sid, "provider": provider, "model": MODELS[provider]["name"],
            "prompt": prompt, "response": response, "error": None,
            "elapsed_sec": round(elapsed, 2), "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        elapsed = time.time() - t0
        return {
            "story_id": sid, "provider": provider, "model": MODELS[provider]["name"],
            "prompt": prompt, "response": None, "error": str(e),
            "elapsed_sec": round(elapsed, 2), "timestamp": datetime.now().isoformat(),
        }



def estimate_cost(work, providers, MODELS):
    avg_input_tokens = 80
    avg_output_tokens = 300
    total_cost = 0
    for provider in providers:
        n = sum(1 for w in work if w[0] == provider)
        if n == 0:
            continue
        m = MODELS[provider]
        cost = n * (avg_input_tokens * m["input_per_mtok"] / 1e6 +
                    avg_output_tokens * m["output_per_mtok"] / 1e6)
        total_cost += cost
        print(f"  {m['name']:25s}: {n:,} queries, ~${cost:.2f}")
    print(f"  {'TOTAL':25s}: {len(work):,} queries, ~${total_cost:.2f}")
    return total_cost


def main():
    parser = argparse.ArgumentParser(description="Track 1: Citation Audit")
    parser.add_argument("--model", choices=["economy", "flagship"], default="economy",
                        help="Model tier (default: economy)")
    parser.add_argument("--lang", choices=["en", "fr"], default="en",
                        help="Story language (default: en)")
    parser.add_argument("--test", type=int, metavar="N",
                        help="Test mode: run only N stories")
    parser.add_argument("-p", "--providers", nargs="+",
                        help="Only run these providers (default: all 4)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show cost estimate without running")
    parser.add_argument("--workers", type=int, default=16,
                        help="Max parallel workers (default: 16)")
    args = parser.parse_args()

    # Import the right query module based on model tier
    if args.model == "flagship":
        from query_flagship import MODELS, query_one
        import query_flagship as _q
        for _p in MODELS:
            try:
                getattr(_q, f"_get_{_p}_client", lambda: None)()
            except Exception:
                pass
        # Warm up OpenAI flagship to avoid threading module-lock issues
        try:
            _q._get_openai_client().chat.completions.create(
                model=MODELS["openai"]["model_id"],
                messages=[{"role": "user", "content": "hi"}], max_tokens=1
            )
        except Exception:
            pass
    else:
        from query import MODELS, query_one
        import query as _q
        for _p in MODELS:
            getattr(_q, f"_get_{_p}_client", lambda: None)()

    paths = get_paths(args.model, args.lang)
    system_prompt = SYSTEM_PROMPTS[args.lang]
    print(f"Model tier: {args.model}  |  Language: {args.lang}", flush=True)
    print(f"Prompts: {paths['prompts']}", flush=True)
    print(f"Output:  {paths['output']}", flush=True)

    prompts = load_prompts(paths["prompts"], limit=args.test)
    print(f"Loaded {len(prompts)} prompts", flush=True)

    provider_choices = list(MODELS.keys())
    providers = args.providers or provider_choices
    # Validate provider names against the chosen module
    for p in providers:
        if p not in MODELS:
            parser.error(f"Unknown provider '{p}' for {args.model} tier. "
                         f"Choose from: {provider_choices}")

    completed = load_completed(paths["output"])
    if completed:
        print(f"Already completed: {len(completed)} responses", flush=True)

    work = [
        (provider, p["prompt"], p["story_id"])
        for p in prompts
        for provider in providers
        if (p["story_id"], provider) not in completed
    ]

    total = len(work)
    n_stories = len(set(w[2] for w in work))
    print(f"Remaining: {total} queries ({n_stories} stories × {len(providers)} providers)",
          flush=True)

    if total == 0:
        print("Nothing to do!")
        return

    estimate_cost(work, providers, MODELS)

    if args.dry_run:
        return

    t0 = time.time()
    done = 0
    errors = 0

    with open(paths["output"], "a") as out_f:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(query_provider, prov, prompt, sid, MODELS, query_one, system_prompt): (prov, sid)
                for prov, prompt, sid in work
            }

            for future in as_completed(futures):
                result = future.result()

                with write_lock:
                    out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
                    out_f.flush()
                    done += 1
                    if result["error"]:
                        errors += 1

                if args.test:
                    status = "✓" if not result["error"] else "✗"
                    resp_preview = (result["response"] or result["error"] or "")[:120]
                    print(f"  {status} {result['model']:25s} {result['story_id']} "
                          f"({result['elapsed_sec']:.1f}s) {resp_preview}", flush=True)

                if not args.test and done % 100 == 0:
                    elapsed = time.time() - t0
                    rate = done / elapsed if elapsed > 0 else 0
                    eta = (total - done) / rate / 60 if rate > 0 else 0
                    print(f"  {done}/{total} ({done/total*100:.0f}%) | "
                          f"{rate:.1f}/sec | {errors} errors | ETA {eta:.0f}m", flush=True)

    elapsed = time.time() - t0
    print(f"\nDone: {done} responses in {elapsed:.1f}s ({errors} errors)", flush=True)
    print(f"Output: {paths['output']}", flush=True)


if __name__ == "__main__":
    main()
