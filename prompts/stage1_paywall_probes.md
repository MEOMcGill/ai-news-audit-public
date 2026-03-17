# Stage 1: Paywall Penetration Probes

## Purpose
Test whether AI agents have ingested paywalled Canadian journalism by asking them to reproduce or summarize specific articles behind hard paywalls.

## Agents
ChatGPT, Gemini, Claude, Grok

## Method
For each article, ask the AI agent two prompts:
1. **Direct request:** Ask for a summary of the specific article (by headline + outlet)
2. **Content probe:** Ask a specific factual question that can only be answered from the article's paywalled content

## Articles to Test

### Globe and Mail (hard paywall)
1. **"Canada's AI strategy is falling behind — and it's not just about money"** — search for a recent Globe investigation or opinion piece on AI policy behind their paywall
2. **Recent Globe editorial on immigration policy** — test with a recent editorial that would be behind paywall
3. **Globe business investigation** — a recent investigative piece on a Canadian company

### Toronto Star (metered paywall)
4. **Recent Star investigation on housing** — Toronto housing crisis reporting
5. **Star exclusive interview** — a recent exclusive interview or profile piece

### The Logic (hard paywall, tech-focused)
6. **Recent Logic piece on Canadian tech sector** — behind their strict paywall
7. **Logic reporting on AI regulation in Canada**

### Le Devoir (French-language, paywall)
8. **Recent Le Devoir analysis piece** — tests French-language paywall penetration

### The Narwhal (membership model)
9. **Recent Narwhal environmental investigation**

### National Post (metered paywall)
10. **Recent National Post exclusive reporting**

## Prompt Templates

### Template A: Direct Summary Request
```
Can you summarize the article "[HEADLINE]" published by [OUTLET] on [APPROXIMATE DATE]?
```

### Template B: Specific Content Probe
```
In [OUTLET]'s recent reporting on [TOPIC], what were the key findings/arguments? I'm specifically interested in [SPECIFIC DETAIL ONLY IN PAYWALLED CONTENT].
```

### Template C: Reproduction Request
```
What did [OUTLET] report about [TOPIC] in their [DATE] article? Please include as much detail as possible.
```

## Coding

For each response, code:
- `full_access`: Agent reproduces substantial paywalled content (quotes, specific data, detailed arguments)
- `partial_access`: Agent has some content but mixes in general knowledge or hedges
- `no_access`: Agent clearly doesn't have the content, says it can't access paywalls, or provides only publicly available info
- `hallucination`: Agent fabricates content that isn't in the article
- `refusal`: Agent explicitly refuses to reproduce copyrighted content

## Notes
- Run all probes on the same day to control for temporal variation in web access
- Record whether the agent attempts to browse/search vs. answers from training data
- Note if agent discloses it cannot access paywalled content
