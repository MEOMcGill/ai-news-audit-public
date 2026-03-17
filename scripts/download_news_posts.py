"""
Download all news_outlet posts from MEO Elasticsearch in small chunks.

Uses direct ES connection (which works) and filters by seed.MainType = news_outlet.
Saves checkpoint chunks every 10k posts. Supports resume.
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from elasticsearch import Elasticsearch

# --- Config ---
MEO_ES_HOST = "15.156.7.112"
MEO_ES_PORT = 9200
MEO_ES_INDEX = "meo_embed_dashboard"
MEO_ES_USERNAME = os.environ.get("MEO_ES_USERNAME", "elastic")
MEO_ES_PASSWORD = os.environ.get("MEO_ES_PASSWORD", "meoelastic")

OUTPUT_DIR = Path(__file__).parent.parent / "data"
CHUNKS_DIR = OUTPUT_DIR / "chunks"
CHECKPOINT_SIZE = 10_000
SCROLL_BATCH = 2000


def get_es_client():
    return Elasticsearch(
        [f"https://{MEO_ES_HOST}:{MEO_ES_PORT}"],
        http_auth=(MEO_ES_USERNAME, MEO_ES_PASSWORD),
        verify_certs=False,
        ssl_show_warn=False,
        timeout=120,
        retry_on_timeout=True,
    )


def flatten_post(p):
    seed = p.get("seed", {})
    if isinstance(seed, dict):
        seed_id = seed.get("SeedID", "")
        seed_name = seed.get("SeedName", "")
        main_type = seed.get("MainType", "")
        sub_type = seed.get("SubType", "")
        province = seed.get("Province", "")
        collection = seed.get("Collection", "")
        handle = seed.get("Handle", "")
        news_category = seed.get("NewsOutletCategory", "")
    else:
        seed_id = seed
        seed_name = main_type = sub_type = province = collection = handle = news_category = ""

    text = p.get("message") or p.get("text_all") or p.get("post") or p.get("description") or ""

    return {
        "id": p.get("id", ""),
        "platform": p.get("platform", ""),
        "date": p.get("date", ""),
        "text": text,
        "title": p.get("title", ""),
        "like_count": p.get("like_count", 0) or 0,
        "share_count": p.get("share_count", 0) or 0,
        "comment_count": p.get("comment_count", 0) or 0,
        "view_count": p.get("view_count", 0) or 0,
        "seed_id": seed_id,
        "seed_name": seed_name,
        "main_type": main_type,
        "sub_type": sub_type,
        "province": province,
        "collection": collection,
        "handle": handle,
        "news_category": news_category,
        "user_name": p.get("user_name", ""),
        "urls": json.dumps(p.get("urls", [])) if p.get("urls") else "",
        "hashtags": json.dumps(p.get("hashtags", [])) if p.get("hashtags") else "",
    }


def save_chunk(rows, chunk_num):
    df = pd.DataFrame(rows)
    path = CHUNKS_DIR / f"chunk_{chunk_num:04d}.parquet"
    df.to_parquet(path, index=False)
    print(f"  Saved chunk {chunk_num}: {len(rows):,} posts -> {path.name}", flush=True)
    return path


def main():
    print("=" * 60, flush=True)
    print("MEO News Outlet Posts Download (Direct ES)", flush=True)
    print(f"Started: {datetime.now().isoformat()}", flush=True)
    print("=" * 60, flush=True)

    OUTPUT_DIR.mkdir(exist_ok=True)
    CHUNKS_DIR.mkdir(exist_ok=True)

    es = get_es_client()
    info = es.info()
    print(f"Connected to ES cluster: {info.get('cluster_name')}, v{info['version']['number']}", flush=True)

    # Probe for the right query
    print("\nProbing query options...", flush=True)
    queries = [
        ("seed.MainType.keyword=news_outlet", {"term": {"seed.MainType.keyword": "news_outlet"}}),
        ("seed.MainType=news_outlet", {"term": {"seed.MainType": "news_outlet"}}),
    ]

    query = None
    total = 0
    for label, q in queries:
        try:
            c = es.count(index=MEO_ES_INDEX, body={"query": {"bool": {"must": [q]}}})["count"]
            print(f"  {label}: {c:,}", flush=True)
            if c > 0 and total == 0:
                query = {"bool": {"must": [q]}}
                total = c
        except Exception as e:
            print(f"  {label}: ERROR {e}", flush=True)

    if not query:
        print("ERROR: No working query. Checking sample doc...", flush=True)
        sample = es.search(index=MEO_ES_INDEX, size=1)
        if sample["hits"]["hits"]:
            src = sample["hits"]["hits"][0]["_source"]
            print(f"  seed field: {json.dumps(src.get('seed', 'MISSING'), default=str)[:300]}", flush=True)
        sys.exit(1)

    print(f"\nTotal news_outlet posts: {total:,}", flush=True)
    print(f"Will save in chunks of {CHECKPOINT_SIZE:,}", flush=True)

    # Scroll download
    start_time = time.time()
    chunk_num = 0
    buffer = []
    downloaded = 0

    print("\nStarting scroll...", flush=True)
    resp = es.search(
        index=MEO_ES_INDEX,
        body={"query": query},
        size=SCROLL_BATCH,
        scroll="10m",
        _source_excludes=["embeddings"],
    )

    scroll_id = resp["_scroll_id"]
    hits = resp["hits"]["hits"]

    while hits:
        for h in hits:
            buffer.append(flatten_post(h["_source"]))
        downloaded += len(hits)

        # Save full chunks
        while len(buffer) >= CHECKPOINT_SIZE:
            chunk_num += 1
            save_chunk(buffer[:CHECKPOINT_SIZE], chunk_num)
            buffer = buffer[CHECKPOINT_SIZE:]

        # Progress
        elapsed = time.time() - start_time
        rate = downloaded / elapsed if elapsed > 0 else 0
        eta = (total - downloaded) / rate if rate > 0 else 0
        pct = downloaded / total * 100
        print(f"  {downloaded:,}/{total:,} ({pct:.0f}%) | {rate:.0f}/sec | ETA {eta/60:.1f}m", flush=True)

        resp = es.scroll(scroll_id=scroll_id, scroll="10m")
        scroll_id = resp["_scroll_id"]
        hits = resp["hits"]["hits"]

    # Save remaining
    if buffer:
        chunk_num += 1
        save_chunk(buffer, chunk_num)

    es.clear_scroll(scroll_id=scroll_id)

    elapsed = time.time() - start_time
    print(f"\nDownload complete: {downloaded:,} posts in {chunk_num} chunks ({elapsed/60:.1f} min)", flush=True)

    # Merge chunks
    print("\nMerging chunks...", flush=True)
    chunks = sorted(CHUNKS_DIR.glob("chunk_*.parquet"))
    dfs = [pd.read_parquet(c) for c in chunks]
    df = pd.concat(dfs, ignore_index=True)

    parquet_path = OUTPUT_DIR / "news_posts.parquet"
    df.to_parquet(parquet_path, index=False)
    print(f"Saved: {parquet_path} ({parquet_path.stat().st_size / 1024 / 1024:.1f} MB)", flush=True)

    # Summary
    print("\n" + "=" * 60, flush=True)
    print("SUMMARY", flush=True)
    print("=" * 60, flush=True)
    print(f"Total posts: {len(df):,}", flush=True)
    print(f"Date range: {df['date'].min()} to {df['date'].max()}", flush=True)
    print(f"\nPlatform breakdown:", flush=True)
    print(df["platform"].value_counts().to_string(), flush=True)
    if df["sub_type"].notna().any():
        print(f"\nSubType breakdown:", flush=True)
        print(df["sub_type"].value_counts().to_string(), flush=True)
    print(f"\nTop 20 outlets:", flush=True)
    if df["seed_name"].notna().any():
        print(df["seed_name"].value_counts().head(20).to_string(), flush=True)
    print(f"\nFinished: {datetime.now().isoformat()}", flush=True)


if __name__ == "__main__":
    main()
