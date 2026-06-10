"""Pre-cache TMDB poster paths for the most popular films into data/posters.json.

The dashboard (app.py) looks posters up by imdb_id and falls back to an on-demand
fetch + placeholder, so this script is purely a warm-up: run it once so the films a
live demo is likely to show resolve instantly (and work even on flaky wifi).

Usage:  python fetch_posters.py            # top 400 by vote_count
        N=800 python fetch_posters.py       # more coverage
"""
import json
import os
import time

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.environ["TMDB_READ_ACCESS_TOKEN"]
HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "data", "films_enriched.csv")
OUT = os.path.join(HERE, "data", "posters.json")
N = int(os.environ.get("N", "400"))

films = pd.read_csv(CSV).sort_values("vote_count", ascending=False).head(N)
try:
    with open(OUT, encoding="utf-8") as f:
        posters = json.load(f)
except Exception:
    posters = {}

session = requests.Session()
session.headers["Authorization"] = f"Bearer {TOKEN}"
fetched = 0
for i, imdb in enumerate(films["imdb_id"]):
    if not isinstance(imdb, str) or imdb in posters:
        continue
    try:
        r = session.get(f"https://api.themoviedb.org/3/find/{imdb}",
                        params={"external_source": "imdb_id"}, timeout=8)
        posters[imdb] = (r.json().get("movie_results") or [{}])[0].get("poster_path")
        fetched += 1
    except Exception:
        posters[imdb] = None
    if fetched and fetched % 25 == 0:
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(posters, f)
        print(f"  {fetched} fetched…")
    time.sleep(0.06)

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(posters, f)
have = sum(1 for v in posters.values() if v)
print(f"Done. {len(posters)} films cached ({have} with posters) -> {OUT}")
