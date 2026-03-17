"""Show Track 2 results for all agents, organized by article × framing × citation."""
import json
import textwrap

with open("data/track2_responses.jsonl") as f:
    records = [json.loads(l) for l in f]

ARTICLES = {
    "star_mall_condo": {
        "label": "Toronto Star (paywalled): Mall Condo Meltdown",
        "facts": {
            "Wojtiw": "wojtiw",
            "Cloverdale": "cloverdale",
            "<10% presold": ["10%", "10 per", "less than 10"],
            "QuadReal": "quadreal",
            "Woodbine": "woodbine",
            "Mattamy": "mattamy",
            "Pickering": "pickering",
            "Aaron Knight": ["aaron knight", "knight, senior"],
        },
        "source_name": "toronto star",
    },
    "cbc_mohawk_ice": {
        "label": "CBC News (free): Mohawk Community & ICE",
        "facts": {
            "Arihhonni David": "arihhonni",
            "Akwesasne": "akwesasne",
            "11-4 vote": ["11 to 4", "11-4", "11 to four"],
            "Rourke": "rourke",
            "Justin Cree": "justin cree",
            "Jay Treaty": "jay treaty",
            "Tom Homan": "homan",
        },
        "source_name": "cbc",
    },
}

FRAMING_LABELS = {"F1": "Generic", "F2": "Specific", "F3": "Direct"}
CITATION_LABELS = {"C0": "Unprompted", "C1": "Cite sources"}
AGENTS_ORDER = ["chatgpt", "gemini", "claude", "grok"]


def check_fact(resp_lower, pattern):
    if isinstance(pattern, list):
        return any(p in resp_lower for p in pattern)
    return pattern in resp_lower


def check_source_cited(resp_lower, citations, source_name):
    """Check if source is cited in API citations or response text."""
    api = any(
        source_name in (c.get("url", "") or "").lower()
        or source_name in (c.get("title", "") or "").lower()
        for c in citations
    )
    text = source_name in resp_lower
    return api, text


for article_id, article_info in ARTICLES.items():
    print(f"\n{'='*80}")
    print(f" {article_info['label']}")
    print(f"{'='*80}")

    for framing in ["F1", "F2", "F3"]:
        for citation in ["C0", "C1"]:
            header = f"{FRAMING_LABELS[framing]} | {CITATION_LABELS[citation]}"
            print(f"\n  --- {header} ---")

            for agent in AGENTS_ORDER:
                matches = [
                    r for r in records
                    if r["article_id"] == article_id
                    and r["agent"] == agent
                    and r["framing"] == framing
                    and r["citation"] == citation
                ]
                if not matches:
                    print(f"    {agent:8s}: [MISSING]")
                    continue

                r = matches[0]
                resp_lower = r["response"].lower()
                citations_api = r.get("citations_from_api", [])

                # Check facts
                facts_found = {}
                for fact_name, pattern in article_info["facts"].items():
                    facts_found[fact_name] = check_fact(resp_lower, pattern)
                n_facts = sum(facts_found.values())
                total_facts = len(article_info["facts"])

                # Check source citation
                api_cited, text_cited = check_source_cited(
                    resp_lower, citations_api, article_info["source_name"]
                )

                # Source display
                if api_cited and text_cited:
                    cite_str = "YES (API+text)"
                elif api_cited:
                    cite_str = "YES (API only)"
                elif text_cited:
                    cite_str = "YES (text only)"
                else:
                    cite_str = "NO"

                fact_names = [k for k, v in facts_found.items() if v]
                print(
                    f"    {agent:8s}: facts={n_facts}/{total_facts} | "
                    f"source cited={cite_str} | "
                    f"${r['cost_usd']:.4f}"
                )
                if fact_names:
                    print(f"              found: {', '.join(fact_names)}")

                # Show first 150 chars of response
                snippet = r["response"][:200].replace("\n", " ")
                print(f"              >>> {snippet}...")

    print()
