# Track 2 Data Pipeline

Full documentation of the Track 2 content theft & attribution probe data collection and validation process.

## Design

**Factorial:** 140 articles × 4 agents × 3 framings × 2 citation conditions = **3,360 responses**

| Factor | Levels |
|--------|--------|
| **Articles** | 140 Canadian news articles from LexisNexis (post-cutoff Feb 2026) |
| **Agents** | ChatGPT (gpt-5-mini), Gemini (gemini-3-flash-preview), Claude (claude-haiku-4-5-20251001), Grok (grok-4-fast-non-reasoning) |
| **Framing** | F1 (Generic), F2 (Specific with distinctive facts), F3 (Direct naming outlet) |
| **Citation** | C0 (Unprompted), C1 ("Please cite your sources") |

All agents have **web search enabled** — testing the real consumer experience.

## File Inventory

### Core Data (Production)

| File | Rows | Description |
|------|------|-------------|
| `track2_articles.jsonl` | 140 | Article metadata + 3 probe variants per article |
| `track2_responses.jsonl` | 3,360 | Raw API responses. Economy tier only, exactly 840 per agent |
| `track2_deterministic.csv` | 3,360 | Deterministic coding: n-gram matching, fact detection, citation parsing |
| `track2_coded.csv` | 3,360 | **Authoritative analysis file.** Deterministic + LLM validation (GPT-5.2) |
| `track2_responses.errors.jsonl` | ~3,000 | Error log from all collection runs (rate limits, quota errors) |
| `coding_schema.md` | — | Defines reproduction and attribution coding levels |

### Batch API Files (Intermediate)

| File | Rows | Description |
|------|------|-------------|
| `track2_coding_batch_input.jsonl` | 1,345 | Last batch input submitted (batch 2) |
| `track2_coding_batch1_output.jsonl` | 839 | Batch 1 output: new backfill responses |
| `track2_coding_batch2_output.jsonl` | 1,344 | Batch 2 output: remaining responses (1 failure) |

### Reference Data

| File | Description |
|------|-------------|
| `lexis_articles.db` | SQLite: full LexisNexis article corpus (~4,000 articles) |
| `lexis_articles.csv` | Metadata export (no body text) |
| `track2_articles_text/` | Individual article text files (52 files) |

### Flagship Recovery (`data_snafu/`)

| File | Rows | Description |
|------|------|-------------|
| `README.md` | — | Full explanation of the data loss incident |
| `track2_responses_flagship_backup.jsonl` | 407 | Recovered raw flagship responses |
| `track2_flagship_recovered.jsonl` | 407 | Same recovery, earlier extraction format |
| `track2_coded_flagship_backup.csv` | 1,345 | LLM codings: 407 matched + 938 against lost responses |

### Archive (`archive.tar.gz`, 14MB compressed)

Previous versions, backups, and intermediate files from the sprint and backfill process.
Extract with `tar xzf archive.tar.gz`. Contents:

| File | Description |
|------|-------------|
| `track2_responses.jsonl.bak` | Sprint-era responses (pre-backfill) |
| `track2_coded.csv.bak` | Sprint-era coded file |
| `track2_coded_o4.csv` | Earlier GPT-4o coded version |
| `track2_deterministic.csv.bak` / `.bak2` | Sprint-era deterministic coding |
| `track2_articles.jsonl.bak` | Earlier article probe set |
| `track2_coding_batch_input_batch1.jsonl` | Sprint batch 1 input |
| `track2_coding_batch_input_recovery.jsonl` | Recovery batch input |
| `track2_coding_batch_input_o4.jsonl` | GPT-4o batch input |
| `track2_batch1_output_sprint.jsonl` | Sprint batch 1 output |
| `track2_batch2_output_sprint.jsonl` | Sprint batch 2 output |
| `track2_coding_batch_output_prev.jsonl` | Previous batch output |
| `track2_coding_batch_output_o4.jsonl` | GPT-4o batch output |
| `track2_coded_pre_download_backup.csv` | Snapshot before batch download overwrote coded file |
| `backup_20260301_track2_coded.csv` | Mar 1 morning snapshot of coded file |
| `backup_20260301_track2_responses.jsonl` | Mar 1 morning snapshot of responses |
| `backup_20260301_track2_coded_flagship_backup.csv` | Flagship coded backup |
| `backup_20260301_track2_responses_flagship_backup.jsonl` | Flagship responses backup |

## Collection Process

### Phase 1: Original Sprint (Feb 27-28, 2026)

Collected ~1,246 economy responses + attempted flagship tier.

**Problems encountered:**
- 696 API failures: 368 OpenAI `insufficient_quota`, 326 Anthropic rate limits
- Root cause: 1s inter-call gap with no retry logic
- A `git checkout` overwrote most flagship responses (see `data_snafu/README.md`)

### Phase 2: Economy Backfill (Mar 1, 2026)

Filled remaining economy cells to reach the full 3,360 factorial.

**Script improvements:**
- Added exponential backoff with 5 retries (`run_track2_probes.py`)
- Increased inter-call gap from 1s → 2s
- Added `--tier economy` flag
- Added concurrent execution for ChatGPT (`backfill_chatgpt.py`, 8 threads)
- Fixed Grok `usd_ticks` cost reporting bug (API returned inflated values)

**Collection runs:**
1. Initial run: ~1,288 new responses across all 4 agents
2. Restart after Claude credit top-up: ~300 more
3. Restart after ChatGPT quota top-up: ~200 more
4. Concurrent ChatGPT backfill: final ~148

**Total API cost:** ~$107

| Agent | Cost | Notes |
|-------|------|-------|
| ChatGPT (gpt-5-mini) | $34.80 | Multiple quota exhaustions, slowest to complete |
| Gemini (gemini-3-flash-preview) | $32.47 | Cleanest run, no errors |
| Claude (claude-haiku-4-5-20251001) | $37.30 | One credit exhaustion mid-run |
| Grok (grok-4-fast-non-reasoning) | $2.34 | Cheapest by far |

### Phase 3: LLM Validation (Mar 1, 2026)

Every response validated by GPT-5.2 via OpenAI Batch API (50% cost discount).

**Coding sources:**
- 1,176 valid codings from original sprint batch (matched to original sprint responses)
- 839 from Batch 1 (new backfill responses)
- 1,344 from Batch 2 (remaining responses, 1 failure)
- 1 direct API call for the single batch failure

**Total: 3,360/3,360 coded. Batch API cost: ~$5.**

### Data Integrity Notes

- 938 economy response keys overlap with lost flagship coded rows. The economy responses
  were re-collected on Mar 1 with **different response text** (non-deterministic APIs).
  Only LLM codings matched to actual response text are in `track2_coded.csv`.
  Stale flagship codings are preserved in `data_snafu/`.

- Gemini reports very low input token counts (~163 avg vs ~25K for ChatGPT/Claude).
  This appears to be a reporting difference, not an actual token difference.

- `cbc_olympics_love_proposals` was removed from the probe set (141 → 140 articles)
  after collection began. 24 orphaned responses were cleaned out.

## Coding Schema

### Deterministic (exact matching)

| Field | Description |
|-------|-------------|
| `facts_found` / `facts_total` | Count of distinctive facts reproduced |
| `verbatim_sequences` | Number of 4+ word verbatim matches |
| `max_verbatim_words` | Longest verbatim sequence |
| `source_cited` | Whether the outlet was named in the response |
| `det_reproduction` | Deterministic reproduction level: extensive/moderate/partial/minimal/none |
| `has_url` / `has_cdn_url` | Whether response contains URLs / Canadian news URLs |

### LLM Validation (GPT-5.2)

| Field | Values |
|-------|--------|
| `llm_reproduction` | verbatim, close_paraphrase, partial, topic_only, none |
| `llm_attribution` | full, outlet_named, vague, none, misattribution |
| `llm_link_quality` | working, broken, hallucinated, none |
| `llm_accuracy` | accurate, mostly_accurate, inaccurate, unverifiable |
| `llm_paywall_reproduced` | true / false |
| `llm_sources_mentioned` | Pipe-separated list of sources named |
| `llm_canadian_sources` | Count of Canadian sources cited |
| `llm_non_canadian_sources` | Count of non-Canadian sources cited |

## Scripts

| Script | Purpose |
|--------|---------|
| `run_track2_probes.py` | Main collection script. 4 agents in parallel threads, retry logic, `--tier` flag |
| `backfill_chatgpt.py` | Concurrent ChatGPT-only collection (8 threads) |
| `generate_article_probes.py` | Generate F1/F2/F3 probe variants from LexisNexis articles |
| `select_track2_articles.py` | Interactive article selection from Lexis corpus |
| `code_responses.py` | Deterministic coding + OpenAI Batch API pipeline (`deterministic`, `prepare`, `submit`, `status`, `download`, `summary`) |

## Reproducibility

The responses are **not reproducible** — all 4 agents use web search and produce
non-deterministic outputs. The coded data (`track2_coded.csv`) is the authoritative
record. Raw responses are preserved in `track2_responses.jsonl` for verification.

Batch API outputs are preserved (`track2_coding_batch1_output.jsonl`,
`track2_coding_batch2_output.jsonl`) to enable re-merging if needed.
