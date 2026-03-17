"""
Extract top 2 English + 1 French Canadian news stories per day from MEO social media data.

For each day: pull national news outlet posts, filter to Canadian content,
cluster by TF-IDF similarity, rank by outlet breadth, output top 2 English
and top 1 French with engagement stats and original posts.

Study period: Jan 1 2024 – Feb 15 2026
"""

import sqlite3
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import AgglomerativeClustering

DB_PATH = "/Users/mcgill/Documents/GitHub/dt_data/social_media.db"
OUTPUT_DIR = Path(__file__).parent.parent / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

START_DATE = datetime(2024, 1, 1)
END_DATE = datetime(2026, 2, 16)

CANADA_KW = re.compile(
    r'\b(canada|canadian|canadians|ottawa|cdnpoli'
    r'|ontario|quebec|québec|british columbia|alberta|manitoba|saskatchewan'
    r'|nova scotia|new brunswick|newfoundland|labrador|pei|prince edward island'
    r'|yukon|nunavut|northwest territories'
    r'|toronto|montreal|montréal|vancouver|calgary|edmonton|winnipeg|halifax'
    r'|victoria|regina|saskatoon|quebec city'
    r'|trudeau|poilievre|carney|doug ford|jagmeet singh|blanchet'
    r'|freeland|joly|guilbeault|champagne|anand|leblanc|holland'
    r'|danielle smith|david eby|françois legault|wab kinew|scott moe|tim houston'
    r'|bank of canada|cbc|ctv|rcmp|parliament hill|house of commons|senate'
    r'|supreme court of canada)\b', re.IGNORECASE
)


def load_seeds(db):
    """Load national news outlet seed metadata."""
    seeds = db.execute('SELECT seed_id, metadata FROM seeds').fetchall()
    seed_meta = {}
    national_ids = set()
    for sid, meta in seeds:
        try:
            m = json.loads(meta)
            if m.get('MainType') == 'news_outlet' and m.get('SubType') == 'national':
                national_ids.add(sid)
                seed_meta[sid] = m
        except:
            pass
    return national_ids, seed_meta


FRENCH_MARKERS = ['le ', 'la ', 'les ', 'des ', 'est ', 'une ', 'dans ']


def _is_french(text_lower):
    return sum(1 for w in FRENCH_MARKERS if w in text_lower) >= 3


def _cluster_posts(posts, stop_words, min_posts=10, min_cluster=3, min_outlets=2):
    """Cluster posts by TF-IDF similarity. Returns ranked story list."""
    if len(posts) < min_posts:
        return []

    # Total engagement for this post set (used for engagement_pct relative to full day)
    texts = [p['text_clean'] for p in posts]
    try:
        vec = TfidfVectorizer(
            max_features=3000, stop_words=stop_words,
            min_df=2, max_df=0.3, ngram_range=(1, 2)
        )
        tfidf = vec.fit_transform(texts)
    except ValueError:
        return []

    norms = np.array(tfidf.power(2).sum(axis=1)).flatten()
    nonzero = norms > 0
    tfidf_clean = tfidf[nonzero]
    posts_clean = [p for p, nz in zip(posts, nonzero) if nz]

    if len(posts_clean) < 5:
        return []

    agg = AgglomerativeClustering(
        n_clusters=None, distance_threshold=0.7,
        metric='cosine', linkage='average'
    )
    labels = agg.fit_predict(tfidf_clean.toarray())

    stories = []
    for c in set(labels):
        members = [i for i, l in enumerate(labels) if l == c]
        if len(members) < min_cluster:
            continue
        outlets = set(posts_clean[i]['outlet'] for i in members)
        if len(outlets) < min_outlets:
            continue

        cluster_eng = sum(posts_clean[i]['engagement'] for i in members)
        best = max(members, key=lambda i: posts_clean[i]['engagement'])

        cluster_tfidf = tfidf_clean[members].mean(axis=0).A1
        top_terms = [vec.get_feature_names_out()[j]
                     for j in cluster_tfidf.argsort()[-5:][::-1]]

        cluster_posts = []
        for i in members:
            p = posts_clean[i]
            cluster_posts.append({
                'id': p['id'],
                'platform': p['platform'],
                'outlet': p['outlet'],
                'text': p['text'],
                'likes': p['likes'],
                'shares': p['shares'],
                'comments': p['comments'],
            })
        cluster_posts.sort(key=lambda x: -(x['likes'] + x['shares'] + x['comments']))

        stories.append({
            'n_posts': len(members),
            'n_outlets': len(outlets),
            'outlets': sorted(outlets),
            'engagement': cluster_eng,
            'cluster_eng': cluster_eng,  # saved before pct conversion
            'terms': top_terms,
            'headline': posts_clean[best]['text'][:300],
            'posts': cluster_posts,
        })

    stories.sort(key=lambda x: (-x['n_outlets'], -x['engagement']))
    return stories


def extract_stories_for_day(db, national_ids, seed_meta, day_start, day_end):
    """Extract top 2 English + top 1 French Canadian stories for a single day."""
    rows = db.execute(
        'SELECT id, platform, seed_id, text_all, like_count, share_count, comment_count '
        'FROM posts WHERE date >= ? AND date < ?',
        (day_start, day_end)
    ).fetchall()

    # Total engagement across ALL posts this day (for % calc)
    total_day_engagement = sum((r[4] or 0) + (r[5] or 0) + (r[6] or 0) for r in rows)

    en_posts = []
    fr_posts = []
    for r in rows:
        if r[2] not in national_ids:
            continue
        t = (r[3] or "").strip()
        if len(t) < 30:
            continue
        if not CANADA_KW.search(t):
            continue
        t_lower = t.lower()
        t_clean = re.sub(r'https?://\S+', '', t)
        t_clean = re.sub(r'@\w+', '', t_clean)
        t_clean = re.sub(r'#[\w]+', '', t_clean)
        eng = (r[4] or 0) + (r[5] or 0) + (r[6] or 0)
        post = {
            'id': r[0], 'platform': r[1], 'seed_id': r[2],
            'text': t, 'text_clean': t_clean[:250],
            'likes': r[4] or 0, 'shares': r[5] or 0, 'comments': r[6] or 0,
            'engagement': eng,
            'outlet': seed_meta.get(r[2], {}).get('SeedName', '')
        }
        if _is_french(t_lower):
            fr_posts.append(post)
        else:
            en_posts.append(post)

    en_stories = _cluster_posts(en_posts, stop_words='english')
    fr_stories = _cluster_posts(fr_posts, stop_words='french', min_posts=5, min_cluster=2, min_outlets=1)

    # Attach engagement_pct and language tag
    results = []
    for s in en_stories[:2]:
        s['engagement_pct'] = (s['cluster_eng'] / total_day_engagement * 100) if total_day_engagement > 0 else 0
        s['language'] = 'en'
        results.append(s)
    for s in fr_stories[:1]:
        s['engagement_pct'] = (s['cluster_eng'] / total_day_engagement * 100) if total_day_engagement > 0 else 0
        s['language'] = 'fr'
        results.append(s)

    return results, total_day_engagement


def main():
    print(f"Extracting top 2 English + 1 French Canadian stories per day", flush=True)
    print(f"Period: {START_DATE.date()} to {END_DATE.date()}", flush=True)

    db = sqlite3.connect(DB_PATH)
    national_ids, seed_meta = load_seeds(db)
    print(f"National news seeds: {len(national_ids)}", flush=True)

    all_stories = []
    day = START_DATE
    n_days = (END_DATE - START_DATE).days
    t0 = time.time()

    while day < END_DATE:
        day_start = int(day.timestamp())
        day_end = int((day + timedelta(days=1)).timestamp())
        date_str = day.strftime("%Y-%m-%d")

        stories, total_eng = extract_stories_for_day(
            db, national_ids, seed_meta, day_start, day_end
        )

        en_rank = 1
        fr_rank = 3  # French story always rank=3
        for s in stories:
            if s['language'] == 'en':
                rank = en_rank
                en_rank += 1
            else:
                rank = fr_rank
            all_stories.append({
                'date': date_str,
                'rank': rank,
                'language': s['language'],
                'terms': ', '.join(s['terms']),
                'headline': s['headline'],
                'n_posts': s['n_posts'],
                'n_outlets': s['n_outlets'],
                'outlets': ', '.join(s['outlets']),
                'engagement': s['engagement'],
                'engagement_pct': round(s['engagement_pct'], 2),
                'total_day_engagement': total_eng,
                'posts_json': json.dumps(s['posts'], ensure_ascii=False),
            })

        days_done = (day - START_DATE).days + 1
        if days_done % 30 == 0 or days_done == 1:
            elapsed = time.time() - t0
            rate = days_done / elapsed
            eta = (n_days - days_done) / rate if rate > 0 else 0
            n_found = len([s for s in all_stories if s['rank'] == 1])
            print(f"  {date_str} | {days_done}/{n_days} days | "
                  f"{n_found} days with stories | "
                  f"{rate:.1f} days/sec | ETA {eta/60:.0f}m",
                  flush=True)

        day += timedelta(days=1)

    db.close()

    # Save
    df = pd.DataFrame(all_stories)
    csv_path = OUTPUT_DIR / "daily_top_stories.csv"
    df.drop(columns=['posts_json']).to_csv(csv_path, index=False)
    print(f"\nSaved summary: {csv_path}", flush=True)

    # Save full version with posts as JSON lines
    jsonl_path = OUTPUT_DIR / "daily_top_stories.jsonl"
    with open(jsonl_path, 'w') as f:
        for _, row in df.iterrows():
            record = row.to_dict()
            record['posts'] = json.loads(record.pop('posts_json'))
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
    print(f"Saved with posts: {jsonl_path}", flush=True)

    # Summary stats
    print(f"\n{'='*60}", flush=True)
    print(f"Total story-days: {len(df)}", flush=True)
    print(f"Days with 2 stories: {len(df[df['rank']==2])}", flush=True)
    print(f"Days with 1 story: {len(df[df['rank']==1]) - len(df[df['rank']==2])}", flush=True)
    print(f"Median outlets per story: {df['n_outlets'].median()}", flush=True)
    print(f"Median engagement per story: {df['engagement'].median():,.0f}", flush=True)
    print(f"Median engagement %: {df['engagement_pct'].median():.1f}%", flush=True)


if __name__ == "__main__":
    main()
