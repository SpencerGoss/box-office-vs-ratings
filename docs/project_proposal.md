# Project Proposal — Box Office vs. Ratings

**Spencer Goss**
*Finalized version (Week 5). The original Week 1 proposal, updated to reflect the
project as actually built — see "How the project evolved" at the end for what changed
and why.*

## Introduction

The movie industry is usually judged by two standards: how much money a film makes and
how much audiences like it. You would assume that these two things would line up
together, but that is not always the case. For people who are looking to create a film,
or are just interested in understanding the movie business in general, comparing these
metrics against each other can open some interesting insights.

## Problem Statement

People making decisions in entertainment — and the general audience — may lack a clear
understanding of why certain movies are being made and why one film genre may be more
beneficial to target than another. This project aims to bridge that gap and understand
the correlation between what a film makes and how the audience perceives it.

## Objectives

- Extract film data from the TMDB API using Python (budget, revenue, audience rating,
  vote count, genre, runtime, release date) for films released 2000–2026.
- Clean and filter the data: drop rows with zero/placeholder budget or revenue, require
  a minimum vote count, and screen out streaming-first releases whose theatrical revenue
  misrepresents their performance.
- Create derived metrics such as profit, return on budget (ROI), profit margin, budget
  tier, and a hit/flop performance classification.
- Store the data in a normalized (3NF) **PostgreSQL** database as the project's source
  of truth, with CSV snapshots exported as a portable fallback.
- Build an interactive analytics dashboard (**Dash + Plotly**) that connects directly to
  PostgreSQL via SQL.
- Identify and document genres or areas where financial and audience reception converge
  or diverge.

## Methodology / Technical Approach

- **API:** The Movie Database (TMDB) API — see `data_source_plan.md` for the full
  data-source plan.
- **Tools:** Python (requests, pandas, SQLAlchemy), PostgreSQL 17, Dash + Plotly.
- **Storage:** PostgreSQL database (`boxoffice`), 3 tables + 1 analytics view in 3NF;
  derived CSV snapshots in `data/`.
- **Data cleaning:** drop zero-budget / zero-revenue rows; require `vote_count >= 100`;
  additionally require budget ≥ $1,000, revenue ≥ $1,000, and revenue ≥ 5% of budget to
  remove placeholder values and streaming-only releases.
- **Visualizations:** scatter plots, KPI cards, interactive filters, bar charts, and a
  per-film breakdown page.
- **Automation:** a single re-runnable ETL pipeline (`etl_pipeline.py`) — extract,
  transform, validate, load — that is idempotent (safe to re-run on demand; `ON CONFLICT`
  upserts never duplicate rows).

**Workflow:**

1. Extract data from the TMDB API with Python (two-stage: discover films by year, then
   fetch per-film financial details).
2. Verify the data is correct and clean rows with missing or placeholder budget/revenue.
3. Filter to a minimum review/vote count and apply the stricter data-quality rules.
4. Create derived variables (profit, ROI, profit margin, budget tier, performance).
5. Validate with automated data-quality checks (nulls, duplicates, dtypes, ranges,
   referential integrity, row-count reconciliation).
6. Load into PostgreSQL with idempotent upserts; export CSV snapshots.
7. Build the interactive Dash dashboard on top of the database.
8. Present findings.

## Timeline

- **Week 1:** Finalize proposal and confirm TMDB API access. Set up GitHub repository.
- **Week 2:** Design the relational schema (ER diagram + documentation) and build the
  initial PostgreSQL load script.
- **Week 3:** Implement the end-to-end ETL pipeline: cleaning, feature engineering,
  validation framework, logging/error handling.
- **Week 4:** Build the interactive dashboard and develop insights from the data.
- **Week 5:** End-to-end validation check; finalize the repository; write up insights
  and prepare the presentation.

## Expected Outcomes

- **Working pipeline:** Python code that runs end-to-end and can be re-run in the future
  to update the dataset on demand.
- **Clean, ready dataset:** a dataset that is easily interpreted and ready for analysis
  (5,659 films after cleaning, from 6,008 extracted).
- **Interactive dashboard:** a Dash application providing high-quality visualizations
  that tell a story, refreshed live from PostgreSQL each time the data updates.
- **Insights on the film industry:** documented findings on how reviews and revenue
  relate to one another, including any surprising results.
- **Projected repository:** a clean, well-structured GitHub repository that is easy to
  understand and can be used to showcase my work.

## How the project evolved from the original proposal

The Week 1 proposal planned a simpler stack. Three things changed as the project matured:

1. **CSV file → PostgreSQL as the source of truth.** The original plan stored the
   cleaned data only as a CSV. Week 2's relational-database requirement (and the reality
   of needing genres as a many-to-many relationship) led to a normalized 3NF PostgreSQL
   schema. The CSV still exists, but as a derived snapshot/fallback exported by the
   pipeline, not as the primary store.
2. **Power BI → Dash + Plotly.** The original plan loaded a CSV into Power BI. The final
   dashboard is instead a Python Dash application that queries PostgreSQL directly —
   which allowed a live demo experience (per-film breakdown pages, poster walls,
   head-to-head comparisons) that a static report couldn't match, while keeping the
   whole project in one reproducible Python stack.
3. **"On demand, no automation" → an automated, idempotent ETL pipeline.** The original
   proposal explicitly planned no automated pipeline. The final project is a single
   self-contained `etl_pipeline.py` that runs extract → transform → validate → load
   end-to-end with logging, retry/backoff, and data-quality checks — re-runnable at any
   time without manual steps.

One planned metric was also refined: the proposed "gap between revenue and ratings"
became concrete as the ratings-vs-returns analysis (median return by rating band) plus
per-film revenue/ROI/rating percentiles on the dashboard's film page.
