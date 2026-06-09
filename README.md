# Box Office vs. Ratings — Interactive Film Analytics

An end-to-end analytics project: a reproducible **Python ETL pipeline** extracts ~6,000
films from the TMDB API (2000–2026), cleans and validates them, and loads them into a
**3NF PostgreSQL** database — which powers an interactive **Dash + Plotly** web
application, themed like a movie theater, for exploring how film budgets, box-office
returns, and audience ratings relate.

**Question:** Do films that earn more also rate higher — and what are the numbers behind
any specific film?

```
TMDB API ─► ETL (clean · validate · load) ─► PostgreSQL (boxoffice, 3NF) ─► Dash app (live SQL)
```

---

## The Dash application — `app.py`

An interactive **film explorer** connected live to PostgreSQL, designed for a live demo:
a dark "movie theater" theme (cinema-gold + teal-and-orange grading), recognizable
content, and a rich page for any individual film.

### Film page (the centerpiece)

Search any film — or click any chart bar, scatter point, or table row — and the top of
the page becomes a full breakdown of that film:

| Panel | What it shows |
|-------|---------------|
| **Poster** | The film's poster (from TMDB, cached locally). |
| **The money** | Budget → Revenue → Profit as a bar, so the scale is instantly readable. |
| **How it ranks vs. all films** | Revenue, ROI, and rating as percentile bars ("top 1%") — context that ties money to ratings for that one film. |
| **Where it sits** | The film's dot highlighted on the ratings-vs-returns scatter of every film. |
| **Headline stats + tier** | Rating, return multiple, ROI, runtime, and a plain-English performance tier (e.g. *"Hit · made 2×+ its budget"*). |

![Film page](docs/screenshots/01-film-page.png)

### Tabs

| Tab | What it does |
|-----|--------------|
| **Top films** | Leaderboards of the biggest box office, biggest profit, best return-on-budget, and biggest losses. Click any bar to open that film. |
| **Compare films** | Pick any two films for a head-to-head: a grouped budget/revenue/profit chart plus a stat table with the winning value highlighted. |
| **Browse films** | A sortable, searchable table of every film; click a row to open it. |
| **Ratings vs. returns** | The core question — a rating-vs-return scatter of every film, plus median return by rating band. |
| **What makes money** | Median ROI by genre and by budget tier, and the overall hit / profitable / flop split. |

![Top films](docs/screenshots/02-top-films.png)
![Compare films](docs/screenshots/03-compare.png)
![What makes money](docs/screenshots/04-what-makes-money.png)

### KPI cards & filters

Six KPIs — **films shown, avg rating, median return, total box office, total profit, and
hit rate (films that earned ≥2× their budget)** — recompute with the filters (genre,
decade, budget tier, and a release-year range), as do every chart and the table.

### How to run

```powershell
# 1. From the project root, activate the virtual environment
.\venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Make sure PostgreSQL is running and loaded (see ETL section below),
#    and that .env has the DB credentials (copy from .env.example).

# 4. (Optional) pre-cache posters for the popular films so they load instantly:
python fetch_posters.py

# 5. Launch the app
python app.py
#    then open http://127.0.0.1:8050
```

### Database integration & demo resilience

The app connects directly to PostgreSQL with SQLAlchemy and runs **one view-based query**
(`v_films_enriched`) at startup / refresh, deriving presentation fields (decade, ROI %,
budget tier, performance) in SQL so the database does the heavy lifting; callbacks then
filter the in-memory frame for instant interactivity. The "Refresh data" button re-queries
the live database.

For a live demo it degrades gracefully: if PostgreSQL is unreachable at startup it
automatically falls back to the `data/films_for_powerbi.csv` snapshot (which mirrors the
view), and the header reflects the active data source. Posters are served from a local
cache (`data/posters.json`); a missing poster fetches once from TMDB and otherwise shows a
placeholder — never a live dependency that can break the demo.

---

## Business insights

- **Better-rated films are far more profitable.** Median return climbs steadily with
  rating: films rated **under 5 lose money**, while films rated **8+ return several times**
  their budget.
- **Bigger budgets pay off.** Blockbusters (>$150M) post the **highest median ROI** *and*
  the best ratings — large bets are well-vetted; the smallest films are the riskiest.
- **Genre matters most.** **Animation** is the sweet spot (high ratings *and* strong
  returns); **Documentaries** post the highest median ROI; Westerns and War the lowest.
- **~45% of films are outright hits** (returning ≥2× their budget).
- **Methodology note:** a naive rating-vs-ROI correlation looks near-zero only because a
  handful of micro-budget films return 100×+, distorting the average — which is why this
  project reports **medians**, not means, throughout.

---

## The data pipeline — `etl_pipeline.py`

A single, self-contained script that runs the full pipeline end-to-end with no manual steps:

| Stage | What it does |
|-------|--------------|
| **Extract** | Reads cached `data/raw/*.json` by default (fast, deterministic). `--refresh` re-pulls from the live TMDB API (two-stage: `/discover/movie` by year → `/movie/{id}` for budget/revenue), with retry + backoff. |
| **Transform** | pandas cleaning, dtype coercion, dedupe, and derived metrics (`profit`, `roi`, `profit_margin`, `budget_tier`, `performance`, `decade`). |
| **Validate** | 7 data-quality checks (API response, null required fields, duplicate keys, dtypes, ranges, referential integrity, row-count reconciliation), each logged PASS/FAIL. |
| **Load** | Idempotent `INSERT … ON CONFLICT` upserts into `films` / `genres` / `film_genres`. Re-running never duplicates. |

```powershell
python etl_pipeline.py            # cached extract → PostgreSQL + CSV
python etl_pipeline.py --refresh  # re-pull from the live TMDB API first
python etl_pipeline.py --csv-only # skip PostgreSQL, only write the CSVs
```

It also exports analytics-ready CSV snapshots (`data/films_for_powerbi.csv`,
`data/genre_decade_summary.csv`) as a portable, no-database fallback.

## Database schema (3NF)

Three tables plus one analytics view — fully documented in
[`schema_documentation.md`](schema_documentation.md) with an ER diagram.

| Table | Purpose |
|-------|---------|
| `films` | One row per movie (financials, runtime, ratings). PK `film_id`, unique `tmdb_id`. |
| `genres` | TMDB genre lookup (19 rows). |
| `film_genres` | M:N bridge resolving films ↔ genres. |
| `v_films_enriched` | View adding `profit`, `roi`, and a comma-joined genre list — consumed directly by the Dash app. |

**Current load:** 6,008 films (2000–2026 YTD) · 19 genres · 15,811 film-genre links.

## Configuration (`.env`)

| Variable | Purpose |
|----------|---------|
| `TMDB_READ_ACCESS_TOKEN` | TMDB v4 bearer token (needed for ETL `--refresh`, a cold cache, and poster fetching) |
| `PG_HOST`, `PG_PORT`, `PG_DATABASE`, `PG_USER`, `PG_PASSWORD` | PostgreSQL connection (database `boxoffice`) |

Secrets live in `.env` (gitignored). `.env.example` is the committed template.

## Tech stack

- Python 3 · pandas · SQLAlchemy 2.0 + psycopg2 · python-dotenv · requests
- **Dash 4 · Plotly 6 · dash-bootstrap-components** (interactive app)
- PostgreSQL 17 (local)

## Repo layout

```
app.py                    Interactive Dash analytics application (the film explorer)
etl_pipeline.py           Full single-file ETL pipeline (extract→transform→validate→load)
fetch_posters.py          One-time TMDB poster pre-cache for the dashboard
schema_documentation.md   Schema docs + ER diagram
load_script.py            Initial PostgreSQL load script (Week 2)
src/extract/              Standalone TMDB fetcher
docs/screenshots/         App screenshots
data/                     CSV snapshots, raw JSON, poster cache (gitignored)
requirements.txt          Python dependencies
```

## Data source

Film data is sourced from [The Movie Database (TMDB) API](https://developer.themoviedb.org/).
This product uses the TMDB API but is not endorsed or certified by TMDB.
