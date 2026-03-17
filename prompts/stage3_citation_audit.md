# Stage 3: Citation Audit — Canadian Current Events

## Purpose
Test whether AI agents cite Canadian news sources when answering questions about Canadian current events. This is the largest empirical component of the brief.

## Agents
ChatGPT, Gemini, Claude, Grok

## Method
Send 40 standardized prompts about Canadian current events across categories. Code every response for citation behavior.

## Prompt Design Principles
- Ask about **Canadian-specific** topics where Canadian outlets should be the primary sources
- Mix timescales: breaking news, ongoing stories, background/explainer questions
- Cover all regions and both official languages
- Include topics where US/international outlets also cover Canada (to test preference)
- Prompts should be natural consumer queries — how a real person would ask

## Prompts by Category

### Federal Politics (8 prompts)
1. "What are the latest developments in Canadian federal politics?"
2. "What is Mark Carney's position on AI regulation?"
3. "What happened in the most recent Canadian federal leaders' debate?"
4. "What is Canada's current policy on immigration levels?"
5. "What are the main issues in Canadian politics right now?"
6. "What is the Canadian government's response to Trump's tariff threats?"
7. "Can you explain Canada's Online News Act and how it's going?"
8. "What's the latest on Canada-US trade relations?"

### Economy & Business (6 prompts)
9. "How is the Canadian housing market doing right now?"
10. "What's happening with the Canadian dollar?"
11. "What are the biggest Canadian tech companies to watch?"
12. "What is Canada's economic outlook for 2026?"
13. "How are Canadian banks performing?"
14. "What's happening with oil prices and the Alberta economy?"

### Provincial & Regional (6 prompts)
15. "What are the key issues in Quebec politics right now?"
16. "What's happening in BC politics?"
17. "What are the main issues in Ontario right now?"
18. "What's happening with healthcare in the Canadian provinces?"
19. "What are the political dynamics in the Prairie provinces?"
20. "What's the latest news from Atlantic Canada?"

### Social Issues & Culture (6 prompts)
21. "What are the major social issues in Canada right now?"
22. "What's happening with Indigenous reconciliation in Canada?"
23. "How is Canada handling the opioid crisis?"
24. "What are the big cultural stories in Canada right now?"
25. "What's the state of Canadian media and journalism?"
26. "What's happening with climate policy in Canada?"

### Science, Tech & Environment (4 prompts)
27. "What is Canada doing on artificial intelligence policy?"
28. "What are the major environmental issues in Canada?"
29. "What Canadian scientific research has been in the news recently?"
30. "How is Canada approaching tech regulation?"

### International / Canada in the World (4 prompts)
31. "What is Canada's role in international affairs right now?"
32. "How is Canada responding to global security challenges?"
33. "What is Canada's foreign policy on China?"
34. "How are other countries covering Canadian politics?"

### Media & Information (4 prompts)
35. "What are the most trusted news sources in Canada?"
36. "How is the Canadian news industry doing?"
37. "What are the best Canadian news outlets to follow for federal politics?"
38. "How does Canadian media coverage differ from American coverage of the same events?"

### Specific Recent Events (2 prompts)
39. "What happened at [SPECIFIC RECENT CANADIAN EVENT]?"
40. "Can you tell me about [SPECIFIC RECENT CANADIAN CONTROVERSY]?"

## Coding Instructions

For each response, code the following fields (see `data/coding_schema.md` for full details):

1. **any_sources**: Does the response cite any sources? (yes/no)
2. **source_count**: Total number of distinct sources cited
3. **canadian_source_count**: Number of Canadian sources cited
4. **non_canadian_source_count**: Number of non-Canadian sources cited
5. **sources_list**: List each source cited with:
   - outlet name
   - country (CA/US/UK/other)
   - link provided (yes/no)
   - link functional (yes/no/NA)
   - named journalist (yes/no)
6. **citation_style**: How are sources referenced? (inline link / named without link / footnote / "according to reports" / none)
7. **accuracy**: Is the factual content accurate? (accurate / mostly accurate / inaccurate / unverifiable)
8. **response_type**: (direct answer / hedged answer / refusal / redirect to search)

## Analysis Plan

### Key Metrics
- **Citation rate**: % of responses that cite any source
- **Canadian citation rate**: % of cited sources that are Canadian
- **Source diversity**: How many distinct Canadian outlets appear across all responses?
- **Link provision rate**: When sources are cited, how often is a link included?
- **Platform comparison**: All metrics broken down by AI agent

### Key Figures (MEO theme)
1. Citation rate by AI agent (bar chart)
2. Canadian vs. non-Canadian source share by agent (stacked bar)
3. Most-cited Canadian outlets (horizontal bar)
4. Citation style by agent (heatmap or grouped bar)
5. Topic variation in Canadian citation rate (faceted or small multiples)
