# Data Source Plan: Box Office vs. Ratings

**Spencer Goss**

## Source

**The Movie Database (TMDB) API**: https://developer.themoviedb.org/

TMDB is a community-maintained film database with a free, well-documented REST API. It
was chosen because it is the only free source that provides budget, revenue, and
audience ratings together for a large catalog of films, with stable IDs and a published
genre taxonomy. (Alternatives considered: OMDb caps free requests at 1,000/day and has
no budget field on most titles; Box Office Mojo has no public API.)

> This product uses the TMDB API but is not endorsed or certified by TMDB.

## Authentication

- TMDB **v4 Read Access Token** (Bearer token), stored in `.env` as
  `TMDB_READ_ACCESS_TOKEN`, never committed; `.env.example` is the committed template.

## Endpoints used (two-stage extract)

The fields the project needs are split across two endpoints, so the extract is
two-stage:

| Stage | Endpoint | What it provides |
|-------|----------|------------------|
| 1, discover | `GET /discover/movie` | Candidate film list: TMDB id, title, release date, vote count/average, popularity, language, genre ids. Paginated by `primary_release_year` (2000–2026) with `vote_count.gte=100`. |
| 2, detail | `GET /movie/{id}` | Per-film financials not exposed by discover: `budget`, `revenue`, `runtime`, `imdb_id`. One call per candidate film. |
| lookup | `GET /genre/movie/list` | The 19-row standardized genre taxonomy. |

## Fields collected

`tmdb_id`, `imdb_id`, `title`, `release_date`, `budget`, `revenue`, `runtime`,
`vote_count`, `vote_average`, `popularity`, `original_language`, `genre_ids`, matching
the analytical needs of the project (financial performance vs. audience rating, by genre
and over time).

## Volume, caching, and refresh strategy

- **Scope:** films released **2000–2026** with at least 100 votes → **6,008 raw films**
  (≈6,100 API calls on a full pull).
- **Caching:** raw API payloads are saved to `data/raw/*.json` (gitignored). The ETL
  reads this cache by default, so repeated runs are fast (~3 s) and deterministic, and
  development never hammers the API.
- **Refresh:** `python etl_pipeline.py --refresh` re-pulls from the live API.
- **Resilience:** API calls use retry with exponential backoff; TMDB's rate limits
  (~50 requests/sec) are respected by the sequential two-stage design.

## Data-quality rules (what gets dropped and why)

Applied in the transform layer (`clean_films()` in `etl_pipeline.py`):

| Rule | Why |
|------|-----|
| `vote_count >= 100` | Ratings from a handful of votes are noise. |
| `budget > 0` and `revenue > 0` | TMDB reports 0 when the value is simply unknown. |
| `budget >= $1,000` and `revenue >= $1,000` | $1–$5 "placeholder" values pass `> 0` but produce absurd ROI. |
| `revenue >= 5% of budget` | Streaming-first films (Netflix/Amazon) record only a token theatrical run (e.g. *The Gray Man*: $200M budget, $0.45M recorded revenue) and would masquerade as nine-figure flops. |
| Implausible runtimes (outside 1–1000 min) | Nulled, not dropped, since runtime is non-critical. |

Result: **6,008 extracted → 5,659 films loaded** (349 dropped, each drop counted and
logged as data-quality evidence).

## Known limitations

- **Theatrical revenue only.** TMDB does not capture streaming revenue; streaming-first
  films are excluded by the 5%-of-budget rule rather than mis-analyzed.
- **Crowd-sourced financials.** Budget/revenue are community-entered and unaudited;
  medians are used throughout the analysis so outliers and data errors don't skew
  results.
- **2026 is partial year-to-date:** only early releases have data and their revenue is
  still climbing, so the dashboard defaults to 2000–2025 and treats 2026 as opt-in.
- **No marketing costs.** "Profit" is revenue minus production budget; prints &
  advertising spend is not public data.
