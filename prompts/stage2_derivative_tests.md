# Stage 2: Derivative Content Analysis

## Purpose
Test whether AI agents produce derivative content based on distinctive Canadian journalism — and whether they attribute the original source.

## Agents
ChatGPT, Gemini, Claude, Grok

## Method
Select recent Canadian news stories with **distinctive original reporting** — investigations, exclusive data, original interviews — where the outlet is the primary or sole source. Ask AI agents general questions on the topic. Compare output to original article for textual similarity, structural borrowing, and factual dependency.

## Selection Criteria for Test Stories
Stories must have:
- Original reporting (not wire copy or aggregation)
- Distinctive facts, quotes, or data not available elsewhere
- Been published within last 3 months
- Clear single-source attribution possible

## Stories to Test

### Category: Investigations
1. **CBC investigation** — a recent CBC Marketplace or investigative unit piece with original data
2. **Globe investigation** — Globe reporting with exclusive documents or data

### Category: Exclusive Interviews
3. **CBC/CTV exclusive interview** — a political interview with original quotes
4. **Toronto Star profile** — long-form profile with original quotes

### Category: Original Data/Analysis
5. **Canadian Press/Global News polling or data story** — original survey or data analysis
6. **CBC data journalism** — a recent data-driven piece

### Category: Breaking News / First Reporting
7. **Canadian outlet breaks a story** — a story first reported by a Canadian outlet
8. **Regional exclusive** — a story from a regional outlet (Winnipeg Free Press, Halifax Chronicle Herald, etc.)

### Category: Opinion/Analysis
9. **Distinctive editorial or analysis** — a piece with a unique analytical frame
10. **Expert commentary** — a piece featuring Canadian expert sources

## Prompt Templates

### Template A: General Topic Question
```
What's happening with [GENERAL TOPIC] in Canada right now?
```
(Where the primary/only source of recent information is the target article)

### Template B: Specific Factual Question
```
[SPECIFIC QUESTION that can only be answered with information from the target article]
```

### Template C: Analysis Request
```
Can you explain the situation with [TOPIC] in Canada? What are the key facts and developments?
```

## Coding

For each response, code:

### Content Dependency
- `high_dependency`: Response clearly derives from the target article (same facts, structure, framing)
- `moderate_dependency`: Some overlap but mixed with other sources
- `low_dependency`: Response draws on general knowledge, not clearly from target article
- `no_dependency`: Response doesn't reflect the article's content at all

### Attribution
- `full_attribution`: Names the outlet and/or journalist, provides link
- `partial_attribution`: Mentions "Canadian media" or "reports" without specifics
- `no_attribution`: Uses the information without any source acknowledgment
- `misattribution`: Credits the wrong source

### Textual Similarity
- Record instances of direct phrasing overlap
- Note structural parallels (same organization of facts)
- Flag distinctive quotes or data points reproduced

## Analysis
- For each story, compute a "derivative score" combining dependency + attribution
- Compare across agents: which ones attribute, which ones reproduce without credit?
- Highlight egregious cases for the brief
