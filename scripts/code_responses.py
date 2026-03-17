#!/usr/bin/env python3
"""
Code Track 2 responses — two layers:

1. DETERMINISTIC (instant): Exact quote matching, fact patterns, source citation
2. LLM-ASSISTED (batch): Paraphrase detection, attribution quality, reproduction assessment

Uses OpenAI Batch API (50% cheaper) for the LLM coding layer.

Usage:
    uv run python scripts/code_responses.py deterministic     # Run exact matching only
    uv run python scripts/code_responses.py prepare            # Generate batch JSONL for LLM coding
    uv run python scripts/code_responses.py submit             # Upload & submit batch
    uv run python scripts/code_responses.py status             # Check batch status
    uv run python scripts/code_responses.py download           # Download & merge results
    uv run python scripts/code_responses.py summary            # Summary tables from coded data
"""

import argparse
import csv
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI

PROJECT_ROOT = Path(__file__).parent.parent
ARTICLES_PATH = PROJECT_ROOT / "data" / "track2_articles.jsonl"
RESPONSES_PATH = PROJECT_ROOT / "data" / "track2_responses.jsonl"
DB_PATH = PROJECT_ROOT / "data" / "lexis_articles.db"

# Deterministic output
DETERMINISTIC_PATH = PROJECT_ROOT / "data" / "track2_deterministic.csv"

# Batch API paths
BATCH_INPUT_PATH = PROJECT_ROOT / "data" / "track2_coding_batch_input.jsonl"
BATCH_OUTPUT_PATH = PROJECT_ROOT / "data" / "track2_coding_batch_output.jsonl"
BATCH_ID_PATH = PROJECT_ROOT / "data" / ".track2_batch_id"

# Final merged output
CODED_PATH = PROJECT_ROOT / "data" / "track2_coded.csv"

FRAMING_LABELS = {"F1": "Generic", "F2": "Specific", "F3": "Direct"}
CITATION_LABELS = {"C0": "Unprompted", "C1": "Cite sources"}

# Canadian news domains — used to check whether a response links to a Canadian
# news site (as opposed to any arbitrary URL). Cast wide to avoid undercounting.
CDN_NEWS_DOMAINS = {
    # ── Outlets in this study ──
    "cbc.ca", "ici.radio-canada.ca", "radio-canada.ca",
    "thestar.com", "torontostar.com",
    "montrealgazette.com",
    "nationalpost.com", "financialpost.com",
    "thelogic.co",
    # ── Wire service ──
    "thecanadianpress.com", "thecanadianpressnews.ca",
    # ── Major national outlets ──
    "globeandmail.com", "theglobeandmail.com",
    "ctvnews.ca", "ctv.ca",
    "globalnews.ca",
    "macleans.ca",
    "bnnbloomberg.ca",
    "citynews.ca",
    "lapresse.ca",
    # ── Yahoo Canada ──
    "ca.news.yahoo.com", "ca.finance.yahoo.com", "ca.sports.yahoo.com",
    # ── Bell Media ──
    "cp24.com",
    # ── Postmedia chain ──
    "torontosun.com", "ottawacitizen.com", "calgaryherald.com",
    "vancouversun.com", "stalbertgazette.com",
    # ── Regional / independent ──
    "winnipegfreepress.com", "saltwire.com", "timescolonist.com",
    "thetyee.ca", "paherald.sk.ca", "squamishchief.com",
    "medicinehatnews.com", "guelphtoday.com", "lethbridgenewsnow.com",
    "lethbridgeherald.com", "coastreporter.net", "rmoutlook.com",
    "torontotoday.ca", "thereview.ca", "obj.ca", "renx.ca",
    "northeastnow.com", "storeys.com", "retail-insider.com",
    "tumblerridgelines.com",
    # ── Indigenous news ──
    "nunatsiaq.com", "aptnnews.ca", "aptntv.ca",
    # ── Political / policy ──
    "ipolitics.ca", "thehub.ca", "policyoptions.irpp.org",
    "westernstandard.news", "thewalrus.ca", "helm.news",
    # ── Sports / specialty ──
    "sportsnet.ca", "thehockeynews.com",
    # ── Public broadcasting ──
    "tvo.org",
    # ── Urban / lifestyle ──
    "blogto.com", "torontolife.com", "vancouverisawesome.com",
    # ── Quebec ──
    "lechodelaval.ca",
    # ── Tech / trade / niche ──
    "betakit.com", "canadiandefencereview.com", "theconversation.com",
    "cicnews.com", "stevemunro.ca", "theglitch.ca", "unpublished.ca",
    "lawtimesnews.com", "manitobacooperator.ca", "themanitoban.com",
    "building.ca",
}

SOURCE_SHORT = {
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
}

CODING_SYSTEM_PROMPT = """You are coding AI agent responses for a research study on how AI agents reproduce and attribute Canadian journalism. Be precise and consistent.

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


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_articles():
    articles = {}
    with open(ARTICLES_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                a = json.loads(line)
                articles[a["id"]] = a
    return articles


def load_responses():
    records = []
    with open(RESPONSES_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def get_article_body(db_id):
    if not db_id or not DB_PATH.exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT body FROM articles WHERE id = ?", (db_id,)).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Deterministic coding functions
# ---------------------------------------------------------------------------

def find_verbatim_sequences(article_body, response, min_words=4):
    """Find non-overlapping verbatim n-word sequences."""
    ab_lower = article_body.lower()
    resp_words = response.lower().split()

    matches = []
    for n in range(25, min_words - 1, -1):
        for i in range(len(resp_words) - n):
            seq = ' '.join(resp_words[i:i+n])
            if len(seq) > 15 and seq in ab_lower:
                matches.append((n, seq, i))

    matches.sort(key=lambda x: -x[0])
    used_positions = set()
    unique = []
    for n, seq, start_idx in matches:
        positions = set(range(start_idx, start_idx + n))
        if not positions & used_positions:
            unique.append((n, seq))
            used_positions |= positions
    return unique


def check_fact(resp_lower, pattern):
    if isinstance(pattern, list):
        return any(p in resp_lower for p in pattern)
    return pattern in resp_lower


def has_canadian_news_url(resp_lower, citations_api):
    """Check if response or API citations contain a Canadian news domain URL."""
    url_pattern = re.compile(r'https?://(?:www\.)?([a-z0-9\-]+(?:\.[a-z0-9\-]+)+)')
    # Check response text
    for m in url_pattern.finditer(resp_lower):
        domain = m.group(1)
        # Match against known Canadian news domains (and subdomains)
        for cdn in CDN_NEWS_DOMAINS:
            if domain == cdn or domain.endswith("." + cdn):
                return True
    # Check API-level citations
    for c in (citations_api or []):
        url = (c.get("url", "") or "").lower()
        for m in url_pattern.finditer(url):
            domain = m.group(1)
            for cdn in CDN_NEWS_DOMAINS:
                if domain == cdn or domain.endswith("." + cdn):
                    return True
        # Also check citation title — Gemini uses redirect URLs with the
        # actual news domain stored in the title field
        title = (c.get("title", "") or "").lower().strip()
        for cdn in CDN_NEWS_DOMAINS:
            if title == cdn or title.endswith("." + cdn):
                return True
    return False


def check_source_citation(resp_lower, citations_api, source_name):
    short = SOURCE_SHORT.get(source_name.lower(), source_name.lower())
    api_cited = any(
        short in (c.get("url", "") or "").lower()
        or short in (c.get("title", "") or "").lower()
        for c in (citations_api or [])
    )
    text_cited = short in resp_lower
    if api_cited and text_cited:
        return "api+text"
    elif api_cited:
        return "api_only"
    elif text_cited:
        return "text_only"
    return "none"


def classify_reproduction(verbatim_matches, n_facts_found, total_facts):
    max_v = max((n for n, _ in verbatim_matches), default=0)
    total_v = sum(n for n, _ in verbatim_matches)
    if max_v >= 10 or total_v >= 20:
        return "substantial"
    elif max_v >= 6 or total_v >= 12:
        return "moderate"
    elif max_v >= 4 or n_facts_found >= 3:
        return "partial"
    elif n_facts_found >= 1:
        return "minimal"
    return "none"


def code_deterministic(response_record, article, article_body):
    """Deterministic coding: exact matches only."""
    resp = response_record["response"] or ""
    resp_lower = resp.lower()
    citations_api = response_record.get("citations_from_api", [])

    # Fact patterns — handle both dict and list formats
    fact_patterns = article.get("fact_patterns", {})
    if isinstance(fact_patterns, list):
        fact_patterns = {p: p for p in fact_patterns}
    facts_found = {k: check_fact(resp_lower, v) for k, v in fact_patterns.items()}
    n_facts = sum(facts_found.values())

    # Verbatim sequences
    verbatim = find_verbatim_sequences(article_body, resp) if article_body else []
    max_v = max((n for n, _ in verbatim), default=0)
    total_v = sum(n for n, _ in verbatim)

    # Source citation
    source_cited = check_source_citation(resp_lower, citations_api, article.get("source", ""))

    # Reproduction level
    reproduction = classify_reproduction(verbatim, n_facts, len(fact_patterns))

    return {
        "article_id": response_record["article_id"],
        "source": article.get("source", ""),
        "paywall": article.get("paywall", False),
        "agent": response_record["agent"],
        "framing": response_record["framing"],
        "framing_label": FRAMING_LABELS.get(response_record["framing"], ""),
        "citation": response_record["citation"],
        "citation_label": CITATION_LABELS.get(response_record["citation"], ""),
        "facts_found": n_facts,
        "facts_total": len(fact_patterns),
        "facts_list": "|".join(k for k, v in facts_found.items() if v),
        "verbatim_sequences": len(verbatim),
        "max_verbatim_words": max_v,
        "total_verbatim_words": total_v,
        "longest_verbatim": verbatim[0][1] if verbatim else "",
        "all_verbatim": " ||| ".join(s for _, s in verbatim) if verbatim else "",
        "source_cited": source_cited,
        "det_reproduction": reproduction,
        "has_url": "http" in resp_lower or "www." in resp_lower,
        "has_cdn_url": has_canadian_news_url(resp_lower, citations_api),
        "n_api_citations": len(citations_api or []),
        "response_length": len(resp),
        "cost_usd": response_record.get("cost_usd", 0),
        "input_tokens": (response_record.get("usage") or {}).get("input_tokens", 0),
        "output_tokens": (response_record.get("usage") or {}).get("output_tokens", 0),
    }


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_deterministic(args):
    """Run deterministic coding on all responses."""
    articles = load_articles()
    responses = load_responses()

    bodies = {}
    for aid, a in articles.items():
        db_id = a.get("lexis_db_id")
        if db_id:
            bodies[aid] = get_article_body(db_id)

    coded = []
    for r in responses:
        aid = r["article_id"]
        article = articles.get(aid, {})
        body = bodies.get(aid)
        coded.append(code_deterministic(r, article, body))

    if not coded:
        print("No responses to code.")
        return

    fieldnames = list(coded[0].keys())
    with open(DETERMINISTIC_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(coded)

    print(f"Coded {len(coded)} responses -> {DETERMINISTIC_PATH}")
    _print_quick_summary(coded)


def cmd_prepare(args):
    """Generate batch input JSONL for LLM coding."""
    articles = load_articles()
    responses = load_responses()
    model = args.model

    bodies = {}
    for aid, a in articles.items():
        db_id = a.get("lexis_db_id")
        if db_id:
            bodies[aid] = get_article_body(db_id)

    # Skip already-coded if merged file exists
    coded_keys = set()
    if CODED_PATH.exists():
        with open(CODED_PATH) as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("llm_reproduction"):  # has LLM coding
                    coded_keys.add((row["article_id"], row["agent"], row["framing"], row["citation"]))

    n_written = 0
    seen_keys = set()
    with open(BATCH_INPUT_PATH, "w") as f:
        for r in responses:
            aid = r["article_id"]
            key = (aid, r["agent"], r["framing"], r["citation"])
            if key in coded_keys or key in seen_keys:
                continue
            seen_keys.add(key)

            article = articles.get(aid, {})
            body = bodies.get(aid, "")

            # Build context for the LLM coder
            facts_str = "\n".join(f"- {fact}" for fact in article.get("distinctive_facts", []))
            body_excerpt = (body or "")[:2000]

            user_msg = (
                f"SOURCE ARTICLE:\n"
                f"Outlet: {article.get('source', 'Unknown')}\n"
                f"Headline: {article.get('headline', 'Unknown')}\n"
                f"Date: {article.get('date', 'Unknown')}\n"
                f"Paywall: {'Yes' if article.get('paywall') else 'No'}\n"
                f"Distinctive facts:\n{facts_str}\n\n"
                f"ARTICLE EXCERPT (first 2000 chars):\n{body_excerpt}\n\n"
                f"---\n\n"
                f"PROBE PROMPT ({FRAMING_LABELS.get(r['framing'], r['framing'])}, "
                f"{CITATION_LABELS.get(r['citation'], r['citation'])}):\n"
                f"{r['prompt']}\n\n"
                f"AI AGENT RESPONSE ({r.get('agent_label', r['agent'])}):\n"
                f"{r['response']}"
            )

            custom_id = f"{aid}__{r['agent']}__{r['framing']}__{r['citation']}"

            batch_request = {
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/responses",
                "body": {
                    "model": model,
                    "input": [
                        {"role": "system", "content": CODING_SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    "max_output_tokens": 4096,
                },
            }

            if "mini" in model or "5.2" in model or "5.1" in model:
                batch_request["body"]["reasoning"] = {"effort": "low"}

            f.write(json.dumps(batch_request) + "\n")
            n_written += 1

    print(f"Wrote {n_written} coding requests to {BATCH_INPUT_PATH}")

    # Cost estimate
    avg_input = 1500  # article excerpt + response + prompt
    avg_output = 200
    if "mini" in model:
        cost = n_written * (avg_input * 0.25 / 1e6 + avg_output * 2.00 / 1e6) * 0.5
    else:
        cost = n_written * (avg_input * 2.00 / 1e6 + avg_output * 8.00 / 1e6) * 0.5
    print(f"Estimated batch cost ({model}, 50% discount): ~${cost:.2f}")


def cmd_submit(args):
    """Upload batch input and submit."""
    client = OpenAI()

    print(f"Uploading {BATCH_INPUT_PATH}...")
    with open(BATCH_INPUT_PATH, "rb") as f:
        upload = client.files.create(file=f, purpose="batch")
    print(f"Uploaded: {upload.id}")

    batch = client.batches.create(
        input_file_id=upload.id,
        endpoint="/v1/responses",
        completion_window="24h",
    )
    print(f"Batch submitted: {batch.id}")
    print(f"Status: {batch.status}")

    BATCH_ID_PATH.write_text(batch.id)
    print(f"Batch ID saved to {BATCH_ID_PATH}")


def cmd_status(args):
    """Check batch status."""
    client = OpenAI()
    batch_id = BATCH_ID_PATH.read_text().strip()
    batch = client.batches.retrieve(batch_id)

    print(f"Batch: {batch.id}")
    print(f"Status: {batch.status}")
    print(f"Created: {datetime.fromtimestamp(batch.created_at).strftime('%Y-%m-%d %H:%M:%S')}")
    if batch.request_counts:
        rc = batch.request_counts
        print(f"Progress: {rc.completed}/{rc.total} ({rc.failed} failed)")
    if batch.output_file_id:
        print(f"Output file: {batch.output_file_id}")


def _extract_text(body):
    """Extract output text from batch response body (chat completions format)."""
    choices = body.get("choices", [])
    if choices:
        return choices[0]["message"]["content"].strip()
    # Fallback: /v1/responses format
    for item in body.get("output", []):
        if item.get("type") == "message" and item.get("content"):
            for c in item["content"]:
                if c.get("type") == "output_text":
                    return c["text"].strip()
    raise ValueError("No text found in response body")


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


def cmd_download(args):
    """Download batch results and merge with deterministic coding."""
    client = OpenAI()
    batch_id = BATCH_ID_PATH.read_text().strip()
    batch = client.batches.retrieve(batch_id)

    if batch.status != "completed":
        print(f"Batch not done yet. Status: {batch.status}")
        if batch.request_counts:
            rc = batch.request_counts
            print(f"Progress: {rc.completed}/{rc.total} ({rc.failed} failed)")
        return

    # Download output
    print(f"Downloading output file {batch.output_file_id}...")
    content = client.files.content(batch.output_file_id)
    BATCH_OUTPUT_PATH.write_bytes(content.read())
    print(f"Saved raw output to {BATCH_OUTPUT_PATH}")

    # Parse LLM coding results
    llm_results = {}
    coded = 0
    parse_errors = 0
    api_errors = 0

    with open(BATCH_OUTPUT_PATH) as f:
        for line in f:
            result = json.loads(line)
            custom_id = result["custom_id"]

            if result.get("error"):
                api_errors += 1
                continue

            try:
                body = result["response"]["body"]
                text = _extract_text(body)
                text = _clean_json(text)
                coding = json.loads(text)

                # Parse custom_id: article_id__agent__framing__citation
                parts = custom_id.split("__")
                key = (parts[0], parts[1], parts[2], parts[3])
                llm_results[key] = coding
                coded += 1

            except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
                parse_errors += 1
                if parse_errors <= 10:
                    print(f"  Parse error on {custom_id}: {e}")

    print(f"Parsed {coded} LLM codings ({parse_errors} parse errors, {api_errors} API errors)")

    # Load deterministic coding and merge
    if not DETERMINISTIC_PATH.exists():
        print(f"Run 'deterministic' first to generate {DETERMINISTIC_PATH}")
        return

    merged = []
    with open(DETERMINISTIC_PATH) as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row["article_id"], row["agent"], row["framing"], row["citation"])
            llm = llm_results.get(key, {})

            row["llm_reproduction"] = llm.get("reproduction_level", "")
            row["llm_attribution"] = llm.get("attribution_level", "")
            row["llm_link_quality"] = llm.get("link_quality", "")
            row["llm_accuracy"] = llm.get("factual_accuracy", "")
            row["llm_paywall_reproduced"] = llm.get("paywalled_content_reproduced", "")
            row["llm_sources_mentioned"] = "|".join(llm.get("sources_mentioned", []))
            row["llm_canadian_sources"] = llm.get("canadian_sources_count", "")
            row["llm_non_canadian_sources"] = llm.get("non_canadian_sources_count", "")
            merged.append(row)

    fieldnames = list(merged[0].keys())
    with open(CODED_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged)

    print(f"Merged {len(merged)} rows -> {CODED_PATH}")


def cmd_summary(args):
    """Print summary tables."""
    # Use merged if available, otherwise deterministic
    path = CODED_PATH if CODED_PATH.exists() else DETERMINISTIC_PATH
    if not path.exists():
        print("No coded data. Run: uv run python scripts/code_responses.py deterministic")
        return

    with open(path) as f:
        coded = list(csv.DictReader(f))

    print(f"\nData: {len(coded)} coded responses from {path.name}")

    # Verbatim reproduction by agent × framing
    print(f"\n{'='*90}")
    print(f"  VERBATIM REPRODUCTION: avg words of verbatim text")
    print(f"{'='*90}")
    print(f"  {'Agent':<10s} | {'F1 Generic':>12s} | {'F2 Specific':>12s} | {'F3 Direct':>12s} | {'Overall':>10s}")
    print(f"  {'-'*10}-+-{'-'*12}-+-{'-'*12}-+-{'-'*12}-+-{'-'*10}")
    for agent in ["chatgpt", "gemini", "claude", "grok"]:
        vals = {}
        for framing in ["F1", "F2", "F3"]:
            rows = [c for c in coded if c["agent"] == agent and c["framing"] == framing]
            if rows:
                avg = sum(int(c["total_verbatim_words"]) for c in rows) / len(rows)
                vals[framing] = f"{avg:.1f}"
            else:
                vals[framing] = "-"
        all_rows = [c for c in coded if c["agent"] == agent]
        overall = sum(int(c["total_verbatim_words"]) for c in all_rows) / len(all_rows) if all_rows else 0
        print(f"  {agent:<10s} | {vals.get('F1','-'):>12s} | {vals.get('F2','-'):>12s} | {vals.get('F3','-'):>12s} | {overall:>10.1f}")

    # Verbatim by agent × paywall
    print(f"\n{'='*90}")
    print(f"  VERBATIM REPRODUCTION: avg words by agent × paywall")
    print(f"{'='*90}")
    print(f"  {'Agent':<10s} | {'Free':>10s} | {'Paywall':>10s}")
    print(f"  {'-'*10}-+-{'-'*10}-+-{'-'*10}")
    for agent in ["chatgpt", "gemini", "claude", "grok"]:
        for pw_label, pw_val in [("free", "False"), ("paywall", "True")]:
            rows = [c for c in coded if c["agent"] == agent and c["paywall"] == pw_val]
            if rows:
                vals[pw_label] = f"{sum(int(c['total_verbatim_words']) for c in rows) / len(rows):.1f}"
            else:
                vals[pw_label] = "-"
        print(f"  {agent:<10s} | {vals.get('free','-'):>10s} | {vals.get('paywall','-'):>10s}")

    # Source citation by agent × paywall
    print(f"\n{'='*90}")
    print(f"  SOURCE CITATION RATE by agent × paywall")
    print(f"{'='*90}")
    print(f"  {'Agent':<10s} | {'Free':>14s} | {'Paywall':>14s} | {'Overall':>10s}")
    print(f"  {'-'*10}-+-{'-'*14}-+-{'-'*14}-+-{'-'*10}")
    for agent in ["chatgpt", "gemini", "claude", "grok"]:
        for pw_label, pw_val in [("free", "False"), ("paywall", "True")]:
            rows = [c for c in coded if c["agent"] == agent and c["paywall"] == pw_val]
            cited = sum(1 for c in rows if c["source_cited"] != "none")
            vals[pw_label] = f"{cited}/{len(rows)}" if rows else "-"
        all_rows = [c for c in coded if c["agent"] == agent]
        all_cited = sum(1 for c in all_rows if c["source_cited"] != "none")
        overall = f"{all_cited}/{len(all_rows)}" if all_rows else "-"
        print(f"  {agent:<10s} | {vals.get('free','-'):>14s} | {vals.get('paywall','-'):>14s} | {overall:>10s}")

    # Distinctive facts by agent × framing
    print(f"\n{'='*90}")
    print(f"  DISTINCTIVE FACTS: avg found by agent × framing")
    print(f"{'='*90}")
    print(f"  {'Agent':<10s} | {'F1 Generic':>12s} | {'F2 Specific':>12s} | {'F3 Direct':>12s} | {'Overall':>10s}")
    print(f"  {'-'*10}-+-{'-'*12}-+-{'-'*12}-+-{'-'*12}-+-{'-'*10}")
    for agent in ["chatgpt", "gemini", "claude", "grok"]:
        vals = {}
        for framing in ["F1", "F2", "F3"]:
            rows = [c for c in coded if c["agent"] == agent and c["framing"] == framing]
            if rows:
                avg = sum(int(c["facts_found"]) for c in rows) / len(rows)
                total = sum(int(c["facts_total"]) for c in rows) / len(rows)
                vals[framing] = f"{avg:.1f}/{total:.0f}"
            else:
                vals[framing] = "-"
        all_rows = [c for c in coded if c["agent"] == agent]
        avg_all = sum(int(c["facts_found"]) for c in all_rows) / len(all_rows) if all_rows else 0
        print(f"  {agent:<10s} | {vals.get('F1','-'):>12s} | {vals.get('F2','-'):>12s} | {vals.get('F3','-'):>12s} | {avg_all:>10.1f}")

    # LLM coding summary if available
    if coded[0].get("llm_reproduction"):
        print(f"\n{'='*90}")
        print(f"  LLM-CODED REPRODUCTION LEVEL by agent × framing")
        print(f"{'='*90}")
        for level in ["verbatim", "close_paraphrase", "partial", "topic_only", "none"]:
            counts = {}
            for agent in ["chatgpt", "gemini", "claude", "grok"]:
                rows = [c for c in coded if c["agent"] == agent and c.get("llm_reproduction") == level]
                counts[agent] = len(rows)
            total = sum(counts.values())
            print(f"  {level:<20s}: " + " | ".join(f"{a}: {counts[a]:3d}" for a in ["chatgpt", "gemini", "claude", "grok"]) + f" | total: {total}")


def _print_quick_summary(coded):
    """Quick summary after deterministic coding."""
    print(f"\nReproduction levels:")
    levels = {}
    for c in coded:
        levels[c["det_reproduction"]] = levels.get(c["det_reproduction"], 0) + 1
    for level in ["substantial", "moderate", "partial", "minimal", "none"]:
        n = levels.get(level, 0)
        print(f"  {level:12s}: {n:4d} ({100*n/len(coded):.0f}%)")

    print(f"\nSource citation rates:")
    cite_counts = {}
    for c in coded:
        cite_counts[c["source_cited"]] = cite_counts.get(c["source_cited"], 0) + 1
    for k in ["api+text", "api_only", "text_only", "none"]:
        n = cite_counts.get(k, 0)
        print(f"  {k:12s}: {n:4d} ({100*n/len(coded):.0f}%)")


def main():
    parser = argparse.ArgumentParser(description="Code Track 2 responses")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("deterministic", help="Run exact matching only")

    p_prep = sub.add_parser("prepare", help="Generate batch JSONL for LLM coding")
    p_prep.add_argument("--model", default="gpt-5.2", help="Model (default: gpt-5.2)")

    sub.add_parser("submit", help="Upload & submit batch to OpenAI")
    sub.add_parser("status", help="Check batch status")
    sub.add_parser("download", help="Download & merge results")
    sub.add_parser("summary", help="Summary tables from coded data")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    {
        "deterministic": cmd_deterministic,
        "prepare": cmd_prepare,
        "submit": cmd_submit,
        "status": cmd_status,
        "download": cmd_download,
        "summary": cmd_summary,
    }[args.command](args)


if __name__ == "__main__":
    main()
