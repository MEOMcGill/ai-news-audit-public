"""Generate story timeline data for the website's data transparency section.

Merges track1_prompts.jsonl + track1_prompts_fr.jsonl with track1_coded.jsonl +
track1_coded_gpt_fr.jsonl to produce:

1. storyData.ts  — all stories with per-agent coding metadata (English + French)
2. public/track1-responses.json — full response text for lazy loading in the explorer

Usage:
    uv run python technical_brief/scripts/generate_story_timeline_data.py
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
OUT_FILE = Path(__file__).parent.parent.parent / "website" / "src" / "storyData.ts"

# Public folder for the deployed site (lazy-loaded response text)
PUBLIC_DIR = (
    Path(__file__).parent.parent.parent.parent  # repo root → aide/
    / "aengusb.github.io"
    / "public"
    / "innovations"
    / "ai-news-audit"
)

AGENT_LABELS = {
    "anthropic": "Claude",
    "openai": "ChatGPT",
    "gemini": "Gemini",
    "xai": "Grok",
}


def load_stories(prompts_file: Path, lang: str) -> dict:
    stories = {}
    with open(prompts_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            s = json.loads(line)
            s["lang"] = lang
            stories[s["story_id"]] = s
    return stories


def load_coded(coded_file: Path) -> dict:
    coded = {}
    with open(coded_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            sid = r["story_id"]
            if sid not in coded:
                coded[sid] = {}
            coded[sid][r["provider"]] = r
    return coded


def load_responses(responses_file: Path) -> dict:
    """Load response text, keyed by (story_id, provider)."""
    responses = {}
    with open(responses_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            key = f"{r['story_id']}|{r['provider']}"
            if r.get("response") and not r.get("error"):
                responses[key] = r["response"]
    return responses


def build_story_row(sid: str, s: dict, coded: dict, lang: str) -> dict:
    agents = {}
    for provider in AGENT_LABELS:
        if sid in coded and provider in coded[sid]:
            c = coded[sid][provider]
            agents[provider] = {
                "knowledge": c.get("knowledge_level", "no_knowledge"),
                "accuracy": c.get("accuracy", "unverifiable"),
                "citation": c.get("citation_type", "none"),
                "sources": c.get("sources_cited", []),
            }
        else:
            agents[provider] = None

    outlets_raw = s.get("outlets", "")
    if isinstance(outlets_raw, list):
        outlets = [o.strip() for o in outlets_raw if o.strip()]
    else:
        outlets = [o.strip() for o in str(outlets_raw).split(",") if o.strip()]

    return {
        "id": sid,
        "date": s["date"],
        "lang": lang,
        "headline": s.get("original_headline", s.get("headline", ""))[:200],
        "prompt": s["prompt"],
        "outlets": outlets,
        "nOutlets": s.get("n_outlets", len(outlets)),
        "engagement": s.get("engagement", 0),
        "engagementPct": round(s.get("engagement_pct", 0) * 100, 2),
        "agents": agents,
    }


def main():
    # Load English stories
    en_stories = load_stories(DATA_DIR / "track1_prompts.jsonl", "en")
    en_coded = load_coded(DATA_DIR / "track1_coded.jsonl")
    en_responses = load_responses(DATA_DIR / "track1_responses.jsonl")

    # Load French stories
    fr_stories = load_stories(DATA_DIR / "track1_prompts_fr.jsonl", "fr")
    fr_coded = load_coded(DATA_DIR / "track1_coded_gpt_fr.jsonl")
    fr_responses = load_responses(DATA_DIR / "track1_responses_fr.jsonl")

    print(f"Loaded {len(en_stories)} English stories, {len(fr_stories)} French stories")

    # Build story rows
    rows = []
    for sid in sorted(en_stories.keys()):
        rows.append(build_story_row(sid, en_stories[sid], en_coded, "en"))
    for sid in sorted(fr_stories.keys()):
        rows.append(build_story_row(sid, fr_stories[sid], fr_coded, "fr"))

    # Sort by date then id
    rows.sort(key=lambda r: (r["date"], r["id"]))

    # Write storyData.ts
    lines = []
    lines.append("// Auto-generated story timeline data for data transparency section")
    lines.append(f"// {len(rows)} stories from Track 1 citation audit (English + French)")
    lines.append(f"// Generated: {__import__('datetime').datetime.now().isoformat()[:19]}")
    lines.append("")
    lines.append("export interface StoryAgent {")
    lines.append("  knowledge: 'knowledgeable' | 'partial' | 'no_knowledge' | 'refusal';")
    lines.append("  accuracy: 'accurate' | 'mostly_accurate' | 'inaccurate' | 'unverifiable';")
    lines.append("  citation: 'none' | 'recommended' | 'named_as_source' | 'quoted' | 'vague_reference';")
    lines.append("  sources: string[];")
    lines.append("}")
    lines.append("")
    lines.append("export interface Story {")
    lines.append("  id: string;")
    lines.append("  date: string;")
    lines.append("  lang: 'en' | 'fr';")
    lines.append("  headline: string;")
    lines.append("  prompt: string;")
    lines.append("  outlets: string[];")
    lines.append("  nOutlets: number;")
    lines.append("  engagement: number;")
    lines.append("  engagementPct: number;")
    lines.append("  agents: {")
    lines.append("    anthropic: StoryAgent | null;")
    lines.append("    openai: StoryAgent | null;")
    lines.append("    gemini: StoryAgent | null;")
    lines.append("    xai: StoryAgent | null;")
    lines.append("  };")
    lines.append("}")
    lines.append("")
    lines.append("// eslint-disable-next-line @typescript-eslint/no-explicit-any")
    lines.append(f"export const STORIES = {json.dumps(rows, ensure_ascii=False)} as any as Story[];")
    lines.append("")

    OUT_FILE.write_text("\n".join(lines))
    print(f"Wrote {len(rows)} stories to {OUT_FILE}")

    # Build and write response text JSON for lazy loading
    response_map = {}
    for (stories_dict, responses_dict) in [(en_stories, en_responses), (fr_stories, fr_responses)]:
        for sid in stories_dict:
            for provider in AGENT_LABELS:
                key = f"{sid}|{provider}"
                if key in responses_dict:
                    if sid not in response_map:
                        response_map[sid] = {}
                    response_map[sid][provider] = responses_dict[key]

    responses_out = PUBLIC_DIR / "track1-responses.json"
    if PUBLIC_DIR.exists():
        with open(responses_out, "w") as f:
            json.dump(response_map, f, ensure_ascii=False, separators=(",", ":"))
        size_mb = responses_out.stat().st_size / 1024 / 1024
        print(f"Wrote response text to {responses_out} ({size_mb:.1f}MB)")
        print(f"  Coverage: {len(response_map)} stories with at least one response")
    else:
        print(f"Warning: Public dir not found at {PUBLIC_DIR} — skipping response JSON")
        print("  Run from the repo with the aengusb.github.io subdir available")


if __name__ == "__main__":
    main()
