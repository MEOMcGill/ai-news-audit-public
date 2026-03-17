"""
Extract top 1 French-language Canadian news story per day from MEO social media data.

Parallel to extract_daily_stories.py (English), but for French posts only.
Output: data/daily_top_stories_fr.jsonl

Study period: Jan 1 2024 – Feb 15 2026
"""

import sqlite3
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import AgglomerativeClustering
from stop_words import get_stop_words

FRENCH_STOP_WORDS = get_stop_words('french')

DB_PATH = "/Users/mcgill/Documents/GitHub/dt_data/social_media.db"
OUTPUT_DIR = Path(__file__).parent.parent / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

START_DATE = datetime(2024, 1, 1)
END_DATE = datetime(2026, 2, 16)

CANADA_KW = re.compile(
    r'(canada|canadian|canadien|canadienne|ottawa|cdnpoli'
    r'|ontario|quebec|québec|colombie.britannique|alberta|manitoba|saskatchewan'
    r'|nouvelle.écosse|nouveau.brunswick|terre.neuve|labrador|î\.p\.é|prince edward island'
    r'|yukon|nunavut|territoires.du.nord.ouest'
    r'|toronto|montréal|montreal|vancouver|calgary|edmonton|winnipeg|halifax'
    r'|victoria|regina|saskatoon|ville de québec'
    r'|trudeau|poilievre|carney|doug ford|jagmeet singh|blanchet'
    r'|freeland|joly|guilbeault|champagne|anand|leblanc|holland'
    r'|danielle smith|david eby|legault|wab kinew|scott moe|tim houston'
    r'|banque du canada|src|radio.canada|grc|parlement|chambre des communes|sénat'
    r'|cour suprême du canada)', re.IGNORECASE
)

FRENCH_MARKERS = ['le ', 'la ', 'les ', 'des ', 'est ', 'une ', 'dans ']


def is_french(text_lower):
    return sum(1 for w in FRENCH_MARKERS if w in text_lower) >= 3


# French-language outlets to include regardless of SubType classification
# (many are classified 'local' in the DB but are nationally relevant)
FRENCH_OUTLET_NAMES = {
    'Radio Canada', 'Radio Canada International', 'Francopresse',
    'TVA Nouvelles', 'Noovo Info',
    'La Presse', 'Le Devoir', 'Journal de Montreal', 'Journal de Quebec',
    'La Tribune', 'Le Nouvelliste', 'Le Droit', 'Le Quotidien',
    'Les Affaires', 'QUB Radio', 'Journal Metro',
}


def load_seeds(db):
    seeds = db.execute('SELECT seed_id, metadata FROM seeds').fetchall()
    seed_meta = {}
    french_ids = set()
    for sid, meta in seeds:
        try:
            m = json.loads(meta)
            if m.get('MainType') != 'news_outlet':
                continue
            name = m.get('SeedName', '')
            # Include national French outlets + curated list of major French outlets
            if (m.get('SubType') == 'national' and name in FRENCH_OUTLET_NAMES) or \
               name in FRENCH_OUTLET_NAMES:
                french_ids.add(sid)
                seed_meta[sid] = m
        except:
            pass
    return french_ids, seed_meta


def extract_french_story_for_day(db, french_ids, seed_meta, day_start, day_end):
    """Extract top French-language Canadian story for a single day."""
    rows = db.execute(
        'SELECT id, platform, seed_id, text_all, like_count, share_count, comment_count '
        'FROM posts WHERE date >= ? AND date < ?',
        (day_start, day_end)
    ).fetchall()

    total_day_engagement = sum((r[4] or 0) + (r[5] or 0) + (r[6] or 0) for r in rows)

    fr_posts = []
    for r in rows:
        if r[2] not in french_ids:
            continue
        t = (r[3] or "").strip()
        if len(t) < 30:
            continue
        # Seeds are already French outlets — no need to re-check language.
        # Just filter out clearly English posts (≥5 English-only function words).
        t_lower = t.lower()
        en_markers = sum(1 for w in [' the ', ' and ', ' this ', ' that ', ' with ', ' from '] if w in t_lower)
        if en_markers >= 3:
            continue
        if not CANADA_KW.search(t):
            continue
        t_clean = re.sub(r'https?://\S+', '', t)
        t_clean = re.sub(r'@\w+', '', t_clean)
        t_clean = re.sub(r'#[\w]+', '', t_clean)
        eng = (r[4] or 0) + (r[5] or 0) + (r[6] or 0)
        fr_posts.append({
            'id': r[0], 'platform': r[1], 'seed_id': r[2],
            'text': t, 'text_clean': t_clean[:250],
            'likes': r[4] or 0, 'shares': r[5] or 0, 'comments': r[6] or 0,
            'engagement': eng,
            'outlet': seed_meta.get(r[2], {}).get('SeedName', '')
        })

    if len(fr_posts) < 5:
        return None, total_day_engagement

    texts = [p['text_clean'] for p in fr_posts]
    try:
        vec = TfidfVectorizer(
            max_features=3000, stop_words=FRENCH_STOP_WORDS,
            min_df=2, max_df=0.4, ngram_range=(1, 2)
        )
        tfidf = vec.fit_transform(texts)
    except ValueError:
        return None, total_day_engagement

    norms = np.array(tfidf.power(2).sum(axis=1)).flatten()
    nonzero = norms > 0
    tfidf_clean = tfidf[nonzero]
    posts_clean = [p for p, nz in zip(fr_posts, nonzero) if nz]

    if len(posts_clean) < 3:
        return None, total_day_engagement

    agg = AgglomerativeClustering(
        n_clusters=None, distance_threshold=0.7,
        metric='cosine', linkage='average'
    )
    labels = agg.fit_predict(tfidf_clean.toarray())

    stories = []
    for c in set(labels):
        members = [i for i, l in enumerate(labels) if l == c]
        if len(members) < 2:
            continue
        outlets = set(posts_clean[i]['outlet'] for i in members)
        # French track: accept single outlet (Radio-Canada may dominate)

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
            'engagement_pct': (cluster_eng / total_day_engagement * 100) if total_day_engagement > 0 else 0,
            'terms': top_terms,
            'headline': posts_clean[best]['text'][:300].replace('\n', ' '),
            'posts': cluster_posts,
        })

    stories.sort(key=lambda x: (-x['n_outlets'], -x['engagement']))
    top = stories[0] if stories else None
    return top, total_day_engagement


def main():
    print(f"Extracting top French story per day", flush=True)
    print(f"Period: {START_DATE.date()} to {END_DATE.date()}", flush=True)

    db = sqlite3.connect(DB_PATH)
    french_ids, seed_meta = load_seeds(db)
    print(f"French news seeds: {len(french_ids)}", flush=True)

    all_stories = []
    day = START_DATE
    n_days = (END_DATE - START_DATE).days
    t0 = time.time()
    n_found = 0

    while day < END_DATE:
        day_start = int(day.timestamp())
        day_end = int((day + timedelta(days=1)).timestamp())
        date_str = day.strftime("%Y-%m-%d")

        story, total_eng = extract_french_story_for_day(
            db, french_ids, seed_meta, day_start, day_end
        )

        if story:
            n_found += 1
            all_stories.append({
                'date': date_str,
                'rank': 3,
                'language': 'fr',
                'terms': ', '.join(story['terms']),
                'headline': story['headline'],
                'n_posts': story['n_posts'],
                'n_outlets': story['n_outlets'],
                'outlets': ', '.join(story['outlets']),
                'engagement': story['engagement'],
                'engagement_pct': round(story['engagement_pct'], 2),
                'total_day_engagement': total_eng,
                'posts_json': json.dumps(story['posts'], ensure_ascii=False),
            })

        days_done = (day - START_DATE).days + 1
        if days_done % 30 == 0 or days_done == 1:
            elapsed = time.time() - t0
            rate = days_done / elapsed
            eta = (n_days - days_done) / rate if rate > 0 else 0
            print(f"  {date_str} | {days_done}/{n_days} days | "
                  f"{n_found} days with French story | "
                  f"{rate:.1f} days/sec | ETA {eta/60:.0f}m",
                  flush=True)

        day += timedelta(days=1)

    db.close()

    # Save summary CSV
    df = pd.DataFrame(all_stories)
    csv_path = OUTPUT_DIR / "daily_top_stories_fr.csv"
    df.drop(columns=['posts_json']).to_csv(csv_path, index=False)
    print(f"\nSaved summary: {csv_path}", flush=True)

    # Save full JSONL with posts
    jsonl_path = OUTPUT_DIR / "daily_top_stories_fr.jsonl"
    with open(jsonl_path, 'w') as f:
        for _, row in df.iterrows():
            record = row.to_dict()
            record['posts'] = json.loads(record.pop('posts_json'))
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
    print(f"Saved with posts: {jsonl_path}", flush=True)

    print(f"\n{'='*60}", flush=True)
    print(f"Days with French story: {n_found} / {n_days} ({n_found/n_days*100:.0f}%)", flush=True)
    if len(df):
        print(f"Median outlets per story: {df['n_outlets'].median()}", flush=True)
        print(f"Median engagement per story: {df['engagement'].median():,.0f}", flush=True)
        print(f"Sample headlines:", flush=True)
        for _, r in df.sample(min(5, len(df))).iterrows():
            print(f"  [{r['date']}] {r['headline'][:100]}", flush=True)


if __name__ == "__main__":
    main()
