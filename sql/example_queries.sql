-- ============================================================================
-- Box Office vs. Ratings — verification + example analysis queries
-- Run against the boxoffice database after `python etl_pipeline.py`:
--     psql -U postgres -d boxoffice -f sql/example_queries.sql
-- ============================================================================

-- 1. Row counts (expected: 5,659 films / 19 genres / 14,914 links)
SELECT 'films' AS table_name, COUNT(*) FROM films
UNION ALL SELECT 'genres', COUNT(*) FROM genres
UNION ALL SELECT 'film_genres', COUNT(*) FROM film_genres;

-- 2. The enriched view the dashboard consumes (one wide row per film)
SELECT title, release_year, budget, revenue, profit, ROUND(roi, 2) AS roi,
       vote_average, genres
FROM v_films_enriched
ORDER BY revenue DESC
LIMIT 10;

-- 3. The core thesis: median return on budget by rating band
SELECT FLOOR(vote_average)::int                                   AS rating_band,
       COUNT(*)                                                   AS films,
       ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY roi)::numeric, 2)
                                                                  AS median_return
FROM v_films_enriched
WHERE release_year <= 2025          -- 2026 is partial year-to-date
GROUP BY 1
ORDER BY 1;

-- 4. Median ROI and rating by genre (films can count toward several genres)
SELECT g.name                                                     AS genre,
       COUNT(*)                                                   AS films,
       ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (
             ORDER BY (f.revenue::numeric / f.budget))::numeric, 2) AS median_return,
       ROUND(AVG(f.vote_average), 2)                              AS avg_rating
FROM films f
JOIN film_genres fg ON fg.film_id  = f.film_id
JOIN genres g       ON g.genre_id  = fg.genre_id
WHERE f.release_year <= 2025
GROUP BY g.name
HAVING COUNT(*) >= 50
ORDER BY median_return DESC;

-- 5. Hit rate: share of films returning at least 2x their budget
SELECT ROUND(100.0 * AVG((revenue >= 2 * budget)::int), 1) AS hit_rate_pct
FROM films
WHERE release_year <= 2025;

-- 6. Referential-integrity spot checks (each should return 0)
SELECT COUNT(*) AS orphan_film_links
FROM film_genres fg LEFT JOIN films f ON f.film_id = fg.film_id
WHERE f.film_id IS NULL;

SELECT COUNT(*) AS orphan_genre_links
FROM film_genres fg LEFT JOIN genres g ON g.genre_id = fg.genre_id
WHERE g.genre_id IS NULL;
