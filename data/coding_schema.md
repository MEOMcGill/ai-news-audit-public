# Coding Schema — AI News Audit

## Overview
This schema defines how to code AI agent responses across all three empirical tests. Each response is one row in the dataset.

## Universal Fields (all stages)

| Field | Type | Description |
|-------|------|-------------|
| `response_id` | string | Unique ID: `S{stage}_{agent}_{prompt_num}` (e.g., `S3_chatgpt_01`) |
| `stage` | int | 1 = paywall probe, 2 = derivative test, 3 = citation audit |
| `agent` | string | `chatgpt` / `gemini` / `claude` / `grok` |
| `prompt_id` | string | Reference to prompt in prompts/ files |
| `prompt_text` | string | Exact text sent to agent |
| `response_text` | string | Full text of agent response |
| `response_date` | date | YYYY-MM-DD |
| `web_search_used` | string | Did the agent visibly search the web? `yes` / `no` / `unclear` |
| `coder` | string | Who coded this response |

---

## Stage 1: Paywall Penetration

| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `target_outlet` | string | Outlet name | Which outlet's paywall is being tested |
| `target_article` | string | Headline | Specific article being probed |
| `paywall_type` | string | `hard` / `metered` / `membership` | Type of paywall |
| `access_level` | string | See below | How much paywalled content the agent reproduced |
| `access_notes` | string | Free text | Specific evidence of access or lack thereof |
| `discloses_paywall` | string | `yes` / `no` | Does agent acknowledge it can't access paywalled content? |

### `access_level` values
- `full_access` — Reproduces substantial paywalled content (specific quotes, data, detailed arguments only in paywalled article)
- `partial_access` — Has some content but mixes with general knowledge or hedges
- `no_access` — Clearly doesn't have paywalled content; provides only publicly available info
- `hallucination` — Fabricates content not in the article
- `refusal` — Explicitly refuses to reproduce copyrighted content

---

## Stage 2: Derivative Content

| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `target_outlet` | string | Outlet name | Original reporting outlet |
| `target_article` | string | Headline | Original article |
| `story_type` | string | `investigation` / `exclusive` / `data` / `breaking` / `opinion` | Type of original reporting |
| `content_dependency` | string | See below | How dependent is the response on the target article? |
| `attribution_level` | string | See below | How well is the source attributed? |
| `textual_overlap` | string | `high` / `moderate` / `low` / `none` | Degree of phrasing similarity |
| `quotes_reproduced` | int | Count | Number of distinctive quotes from original reproduced |
| `data_reproduced` | string | `yes` / `no` | Does response reproduce original data/statistics? |
| `derivative_notes` | string | Free text | Specific examples of derivative content |

### `content_dependency` values
- `high` — Response clearly derives from target article (same facts, structure, framing)
- `moderate` — Some overlap but mixed with other sources
- `low` — Draws on general knowledge, not clearly from target article
- `none` — Response doesn't reflect the article's content

### `attribution_level` values
- `full` — Names outlet and/or journalist, provides link
- `partial` — Mentions "Canadian media" or "reports" without specifics
- `none` — Uses information without any source acknowledgment
- `misattribution` — Credits wrong source

---

## Stage 3: Citation Audit

| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `topic_category` | string | `federal_politics` / `economy` / `provincial` / `social` / `science_tech` / `international` / `media` / `specific_event` | Topic category |
| `any_sources` | string | `yes` / `no` | Does response cite any sources? |
| `source_count` | int | Count | Total distinct sources cited |
| `canadian_source_count` | int | Count | Canadian sources cited |
| `non_canadian_source_count` | int | Count | Non-Canadian sources cited |
| `citation_style` | string | See below | How sources are referenced |
| `accuracy` | string | `accurate` / `mostly_accurate` / `inaccurate` / `unverifiable` | Factual accuracy |
| `response_type` | string | `direct` / `hedged` / `refusal` / `redirect` | Nature of response |

### `citation_style` values
- `inline_link` — Source named with clickable URL in text
- `named_no_link` — Source named but no URL
- `footnote` — Sources listed at end
- `vague_reference` — "According to reports" / "media sources say" without specifics
- `none` — No source attribution at all

### Sources Sub-table
For each source cited in a Stage 3 response, record:

| Field | Type | Description |
|-------|------|-------------|
| `response_id` | string | Links to parent response |
| `source_outlet` | string | Name of outlet (e.g., "CBC News") |
| `source_country` | string | `CA` / `US` / `UK` / `other` |
| `link_provided` | string | `yes` / `no` |
| `link_functional` | string | `yes` / `no` / `na` |
| `journalist_named` | string | `yes` / `no` |

---

## Canadian Outlet Reference List

For consistent coding, use these canonical names:

### National
CBC News, CTV News, Global News, The Globe and Mail, Toronto Star, National Post, The Canadian Press, La Presse, Le Devoir, Radio-Canada, Maclean's, The Walrus

### Digital-Native
The Logic, The Narwhal, The Tyee, iPolitics, The Hub, Capital Current, The Conversation Canada

### Regional
Winnipeg Free Press, Halifax Chronicle Herald, Calgary Herald, Edmonton Journal, Vancouver Sun, Ottawa Citizen, Montreal Gazette, StarPhoenix (Saskatoon), Times Colonist (Victoria)

### Wire / International with Canadian Bureau
Reuters (Canada), Associated Press, AFP, BBC, New York Times (Canada bureau), Washington Post

---

## Data File Format

Responses stored as CSV in `data/`:
- `data/stage1_responses.csv`
- `data/stage2_responses.csv`
- `data/stage3_responses.csv`
- `data/stage3_sources.csv` (sub-table for individual source citations)

Use `response_id` as the primary key linking across files.
