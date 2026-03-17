"""Quick check of Track 2 probe results."""
import json

with open("data/track2_responses.jsonl") as f:
    records = [json.loads(l) for l in f]

print(f"Total responses: {len(records)}\n")

for article_id in ["star_mall_condo", "cbc_mohawk_ice"]:
    print(f"{'='*70}")
    print(f"ARTICLE: {article_id}")
    print(f"{'='*70}\n")

    for r in records:
        if r["article_id"] != article_id:
            continue

        resp_lower = r["response"].lower()
        citations = r.get("citations_from_api", [])

        if article_id == "star_mall_condo":
            facts = {
                "Wojtiw": "wojtiw" in resp_lower,
                "Cloverdale": "cloverdale" in resp_lower,
                "<10% presold": "10%" in resp_lower or "10 per" in resp_lower,
                "QuadReal": "quadreal" in resp_lower,
                "Woodbine": "woodbine" in resp_lower,
                "Mattamy": "mattamy" in resp_lower,
                "Pickering": "pickering" in resp_lower,
                "Aaron Knight": "aaron knight" in resp_lower or "knight" in resp_lower,
            }
            source_check = "toronto star"
        else:
            facts = {
                "Arihhonni David": "arihhonni" in resp_lower,
                "Akwesasne": "akwesasne" in resp_lower,
                "St Lawrence 11-4 vote": "11 to 4" in resp_lower or "11-4" in resp_lower,
                "Matthew Rourke": "rourke" in resp_lower,
                "Justin Cree": "justin cree" in resp_lower,
                "Jay Treaty 1794": "jay treaty" in resp_lower,
                "Tom Homan meeting": "homan" in resp_lower,
            }
            source_check = "cbc"

        star_in_api = any(
            source_check in (c.get("url", "") or "").lower()
            or source_check in (c.get("title", "") or "").lower()
            for c in citations
        )
        star_in_text = source_check in resp_lower

        facts_found = sum(1 for v in facts.values() if v)
        found_list = [k for k, v in facts.items() if v]

        print(f"{r['agent']:8s} | {r['framing']} | {r['citation']} | ${r['cost_usd']:.4f}")
        print(f"  Facts: {facts_found}/{len(facts)} — {found_list}")
        print(f"  Source cited: API={star_in_api}, text={star_in_text} | API citations: {len(citations)}")
        # Show citation URLs
        for c in citations[:3]:
            url = c.get("url", "")
            title = (c.get("title", "") or "")[:60]
            print(f"    -> {title} | {url}")
        print()
