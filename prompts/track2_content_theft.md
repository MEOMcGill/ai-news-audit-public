# Track 2: Content Theft & Attribution Probe — February 2026

## Design Rationale

These articles are **post-cutoff** (Feb 2026) — they cannot be in any AI model's training data. If an AI agent reproduces this content, it is **actively retrieving and redistributing** copyrighted Canadian journalism.

We test two things simultaneously:
1. **Theft:** Can agents reproduce distinctive copyrighted content from Canadian outlets?
2. **Attribution:** When they do, do they credit the source? Does asking change behavior?

## Experimental Design

**3 × 2 × 4 × N factorial:**

### Factor 1: Framing (3 levels)

| Level | Name | Description |
|-------|------|-------------|
| F1 | **Generic** | Natural consumer question about the topic. No mention of article, outlet, or specific facts. |
| F2 | **Specific** | Question referencing distinctive facts only available in the article (names, numbers, quotes). Does not name the outlet. |
| F3 | **Direct** | References the headline or outlet explicitly. "I read in the Star that..." |

**Logic:** F1 tests whether agents surface Canadian journalism unprompted. F2 tests whether agents can reproduce exclusive reporting when nudged. F3 tests whether agents will retrieve and summarize a named article.

### Factor 2: Citation Prompt (2 levels)

| Level | Name | Description |
|-------|------|-------------|
| C0 | **Unprompted** | No instruction about sources. |
| C1 | **Prompted** | Append: "Please cite your sources." |

**Logic:** Separates "can they attribute" from "do they attribute by default." If an agent reproduces paywalled Star content without citation unprompted (C0) but correctly attributes when asked (C1), that's a strong finding — the information is accessible but attribution isn't default behavior.

### Factor 3: Agent (4 levels)

| Agent | Company | Web access |
|-------|---------|------------|
| ChatGPT (GPT-4o) | OpenAI | Yes (browsing) |
| Gemini | Google | Yes |
| Claude | Anthropic | Yes (web search) |
| Grok | xAI | Yes |

### Factor 4: Stories (N)

Target: **10–20 articles** selected from the Feb 2026 Lexis corpus. See Article Selection below.

### Total responses: 3 × 2 × 4 × N = 24N

| N stories | Total responses |
|-----------|----------------|
| 10 | 240 |
| 15 | 360 |
| 20 | 480 |

## Prompt Construction

Each article gets **6 prompt variants** (3 framings × 2 citation conditions).

### Template

For each article, an LLM rephrases the headline into a natural consumer query at each framing level. Then each query is run in two versions:

**F1 × C0 (Generic, unprompted):**
```
{generic topic question}
```

**F1 × C1 (Generic, prompted):**
```
{generic topic question} Please cite your sources.
```

**F2 × C0 (Specific, unprompted):**
```
{question referencing distinctive facts from the article}
```

**F2 × C1 (Specific, prompted):**
```
{question referencing distinctive facts from the article} Please cite your sources.
```

**F3 × C0 (Direct, unprompted):**
```
{question naming the outlet/headline}
```

**F3 × C1 (Direct, prompted):**
```
{question naming the outlet/headline} Please cite your sources.
```

## Article Selection

### Selection Criteria
- **Long-form original reporting** (>700 words) — more distinctive content
- **Exclusive facts** — quotes, data, names only available in that article
- **Paywall priority** — Star and Gazette articles are strongest theft signal
- **Topic diversity** — politics, investigations, business, social, culture

### Pre-identification of Distinctive Facts
For each selected article, identify **3–5 distinctive facts** before running probes:
- Named individuals (especially non-public figures)
- Specific dollar amounts, percentages, dates
- Direct quotes
- Locations or organizations unique to the reporting

These become the basis for F2 (Specific) probes and the coding of content reproduction.

### Outlet Balance

| Outlet | Paywall | Target N | Priority |
|--------|---------|----------|----------|
| Toronto Star | Metered paywall | 4–5 | Highest — paywalled original reporting |
| Montreal Gazette | Metered paywall | 3–4 | High — paywalled, some French content |
| CBC (News) | Free | 3–4 | Control — freely available content |
| Radio-Canada | Free (French) | 2–3 | Tests French-language reproduction |

## Coding Schema

### Content Reproduction (per response)
| Code | Definition |
|------|------------|
| `verbatim` | Direct quotes or near-verbatim passages from the article |
| `paraphrase` | Same facts and structure, reworded |
| `partial` | Some article content mixed with other sources or general knowledge |
| `none` | No detectable content from the article |

### Distinctive Facts (per response)
For each of the 3–5 pre-identified distinctive facts per article, code:
- **1** = fact appears in response
- **0** = fact does not appear

This gives a **reproduction score** (0–5) per response.

### Attribution (per response)
| Code | Definition |
|------|------------|
| `full` | Names outlet + journalist, provides link |
| `outlet_only` | Names outlet, no journalist or link |
| `outlet_link` | Names outlet + provides link |
| `vague` | "According to reports" / "Canadian media" / unnamed |
| `none` | No attribution |
| `misattribution` | Credits wrong source |

### Link Quality (if link provided)
| Code | Definition |
|------|------------|
| `working` | Link resolves to the actual article |
| `broken` | Link is malformed or 404 |
| `hallucinated` | Plausible-looking URL that doesn't exist |
| `none` | No link provided |

### Web Search Behavior
| Code | Definition |
|------|------------|
| `searched` | Agent visibly performed web search |
| `no_search` | Agent answered without searching |
| `unclear` | Can't determine |

## Execution Protocol

1. Run all probes on **the same day**
2. **Fresh conversation** for each individual probe (no context bleed between F1/F2/F3 or C0/C1)
3. Use each agent's **default consumer settings** — don't toggle web search
4. **Screenshot** every response
5. Record: agent, article_id, framing (F1/F2/F3), citation_prompt (C0/C1), timestamp

## Analysis Plan

### Primary analyses:

**1. Content reproduction by paywall status**
- Do agents reproduce paywalled (Star, Gazette) content as readily as free (CBC)?
- DV: reproduction score (0–5 distinctive facts)

**2. Attribution by citation prompt (the key finding)**
- C0 vs C1: Does asking "cite your sources" change attribution rates?
- DV: attribution code (full / outlet_only / outlet_link / vague / none)
- If agents reproduce content at C0 without attribution but attribute at C1, the default consumer experience is content theft

**3. Framing × Attribution interaction**
- At F1 (generic), do agents ever spontaneously cite Canadian outlets?
- At F3 (direct), do they acknowledge the named outlet?
- Does the gap between C0 and C1 narrow at F3?

**4. Cross-platform comparison**
- Which agents reproduce the most content?
- Which agents attribute most reliably?
- Which agents provide working links?

### Key policy-relevant findings (if they exist):

1. **Default theft:** Agent reproduces paywalled content without attribution at C0 — the normal consumer experience is receiving stolen journalism
2. **Attribution gap:** Agent can attribute when asked (C1) but doesn't by default (C0) — the technology exists, attribution is a design choice
3. **Paywall bypass:** Agent reproduces paywalled content as readily as free content — paywall provides no protection
4. **Link failure:** Agent provides links that don't work — gives appearance of attribution without actually driving traffic
