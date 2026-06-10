-- ============================================================================
-- Box Office vs. Ratings — PostgreSQL schema (database: boxoffice)
-- 3 tables (3NF) + 1 analytics view.
--
-- NOTE: the canonical copy of this DDL is inlined as the SCHEMA_DDL constant
-- in etl_pipeline.py (and load_script.py), which applies it idempotently on
-- every run. This file is an exported copy for reference / manual psql use:
--     psql -U postgres -d boxoffice -f sql/schema.sql
-- ============================================================================

CREATE TABLE IF NOT EXISTS films (
    film_id            SERIAL       PRIMARY KEY,
    tmdb_id            INTEGER      NOT NULL UNIQUE,
    imdb_id            TEXT,
    title              TEXT         NOT NULL,
    release_date       DATE,
    release_year       INTEGER,
    budget             BIGINT       NOT NULL,
    revenue            BIGINT       NOT NULL,
    runtime            INTEGER,
    vote_count         INTEGER      NOT NULL,
    vote_average       NUMERIC(4,2),
    popularity         NUMERIC(10,3),
    original_language  CHAR(2),
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_budget_positive  CHECK (budget  > 0),
    CONSTRAINT chk_revenue_positive CHECK (revenue > 0),
    CONSTRAINT chk_vote_count       CHECK (vote_count >= 100)
);

CREATE INDEX IF NOT EXISTS idx_films_release_year ON films(release_year);
CREATE INDEX IF NOT EXISTS idx_films_vote_average ON films(vote_average);
CREATE INDEX IF NOT EXISTS idx_films_revenue      ON films(revenue);

CREATE TABLE IF NOT EXISTS genres (
    genre_id  INTEGER  PRIMARY KEY,
    name      TEXT     NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS film_genres (
    film_id   INTEGER  NOT NULL REFERENCES films(film_id)   ON DELETE CASCADE,
    genre_id  INTEGER  NOT NULL REFERENCES genres(genre_id) ON DELETE RESTRICT,
    PRIMARY KEY (film_id, genre_id)
);

CREATE INDEX IF NOT EXISTS idx_film_genres_genre ON film_genres(genre_id);

CREATE OR REPLACE VIEW v_films_enriched AS
SELECT
    f.film_id, f.tmdb_id, f.imdb_id, f.title, f.release_date, f.release_year,
    f.budget, f.revenue,
    (f.revenue - f.budget)                                          AS profit,
    CASE WHEN f.budget > 0 THEN (f.revenue::numeric / f.budget) END AS roi,
    f.runtime, f.vote_count, f.vote_average, f.popularity, f.original_language,
    STRING_AGG(g.name, ', ' ORDER BY g.name)                      AS genres
FROM films f
LEFT JOIN film_genres fg ON fg.film_id = f.film_id
LEFT JOIN genres      g  ON g.genre_id = fg.genre_id
GROUP BY f.film_id;
