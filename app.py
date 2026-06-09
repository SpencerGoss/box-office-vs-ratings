"""Box Office vs. Ratings — Interactive Film Explorer (Dash + Plotly).

An exploration tool over the PostgreSQL `boxoffice` database built by the ETL
pipeline. Look up any of 6,000+ films to see its budget, revenue, profit, ROI
and audience rating; filter by genre / decade / budget / year; and explore how
money and ratings relate across films, genres, budgets, and time.

Run:
    venv\\Scripts\\activate
    python app.py
    # open http://127.0.0.1:8050

Data flow:
    PostgreSQL (v_films_enriched) -> one view-based query at startup / refresh
    -> in-memory pandas -> callbacks filter instantly -> Plotly figures + table.

Requires a .env with PG_HOST/PG_PORT/PG_DATABASE/PG_USER/PG_PASSWORD.
"""
from __future__ import annotations

import json
import os

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
from dash import Dash, Input, Output, State, callback_context, dash_table, dcc, html, no_update
from dotenv import load_dotenv
from plotly.subplots import make_subplots
from sqlalchemy import create_engine, text

# ===========================================================================
# Configuration
# ===========================================================================
load_dotenv()

# ---- "movie theater" palette: warm espresso canvas + the classic teal-and-orange
# film-grading scheme (cinema gold/amber warm, teal as the complementary cool) ----
BG = "#15120C"          # warm espresso-charcoal (a dim theater)
PANEL = "#1F1A12"       # warm dark — cards / chart panels
PANEL_HI = "#2A2318"    # table header, hover, raised bits
BORDER = "#352D20"      # subtle warm border
INK = "#ECE4D3"         # warm cream (primary text)
MUTED = "#A99E88"       # warm grey text
GRID = "#2B2417"        # chart gridlines
GOLD = "#D9A441"        # marquee gold — primary (box office, hits)
ORANGE = "#D07C38"      # warm amber — secondary (returns, ROI)
TEAL = "#46A7A0"        # complementary cool — the teal of teal-and-orange grading
RED = "#C24A42"         # curtain crimson — losses / flops
ACCENT = GOLD
PAGE_BG = BG
SHADOW = "0 2px 10px rgba(0,0,0,0.50)"
FONT = "Inter, Segoe UI, Helvetica, Arial, sans-serif"
HEAD_FONT = "Oswald, Inter, sans-serif"   # condensed, movie-poster feel for titles
PALETTE = [GOLD, TEAL, ORANGE, RED, "#C9A36A", "#7FA59E"]

TIER_ORDER = ["Low (<$10M)", "Mid ($10-50M)", "High ($50-150M)", "Blockbuster (>=$150M)"]
PERF_ORDER = ["Flop (<1x)", "Profitable (1-2x)", "Hit (>=2x)"]
PERF_COLORS = {"Flop (<1x)": RED, "Profitable (1-2x)": GOLD, "Hit (>=2x)": TEAL}
# Plain-English badge text — the raw "Hit (>=2x)" labels are jargon to a demo audience.
PERF_BADGE = {"Flop (<1x)": "Flop · lost money",
              "Profitable (1-2x)": "Profitable · made 1–2× its budget",
              "Hit (>=2x)": "Hit · made 2×+ its budget"}

FILMS_SQL = text("""
    SELECT v.film_id, v.title, v.imdb_id, v.release_year,
           (v.release_year / 10 * 10)::text || 's'                  AS decade,
           v.budget, v.revenue, v.profit,
           ROUND(v.roi, 2)                                          AS revenue_multiple,
           ROUND((v.roi - 1) * 100, 0)                              AS roi_pct,
           CASE WHEN v.budget < 10000000  THEN 'Low (<$10M)'
                WHEN v.budget < 50000000  THEN 'Mid ($10-50M)'
                WHEN v.budget < 150000000 THEN 'High ($50-150M)'
                ELSE 'Blockbuster (>=$150M)' END                    AS budget_tier,
           CASE WHEN v.roi < 1 THEN 'Flop (<1x)'
                WHEN v.roi < 2 THEN 'Profitable (1-2x)'
                ELSE 'Hit (>=2x)' END                               AS performance,
           v.runtime, v.vote_count, v.vote_average, v.genres
    FROM v_films_enriched v
""")


CSV_FALLBACK = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "films_for_powerbi.csv")
DATA_SOURCE = "Live PostgreSQL"  # overwritten by load_films() if the DB is unreachable


def get_engine():
    url = (f"postgresql+psycopg2://{os.environ['PG_USER']}:{os.environ['PG_PASSWORD']}"
           f"@{os.environ['PG_HOST']}:{os.environ['PG_PORT']}/{os.environ['PG_DATABASE']}")
    return create_engine(url, future=True)


def _load_from_db() -> pd.DataFrame:
    with get_engine().connect() as conn:
        return pd.read_sql(FILMS_SQL, conn)


def _load_from_csv() -> pd.DataFrame:
    """Demo-safety fallback: the CSV snapshot mirrors v_films_enriched exactly, so a
    Postgres hiccup mid-presentation can never blank the dashboard. Derives the few
    columns the SQL computes server-side (revenue_multiple, roi_pct) from `roi`."""
    df = pd.read_csv(CSV_FALLBACK).rename(columns={"tmdb_id": "film_id"})
    df["revenue_multiple"] = df["roi"].round(2)
    df["roi_pct"] = ((df["roi"] - 1) * 100).round(0)
    return df


def load_films() -> pd.DataFrame:
    global DATA_SOURCE
    try:
        df = _load_from_db()
        DATA_SOURCE = "Live PostgreSQL"
    except Exception as exc:  # connection refused, auth, driver missing, etc.
        print(f"[warn] Postgres unavailable ({type(exc).__name__}: {str(exc)[:80]}); "
              f"loading CSV snapshot from {CSV_FALLBACK}")
        df = _load_from_csv()
        DATA_SOURCE = "CSV snapshot (Postgres offline)"
    df["budget_tier"] = pd.Categorical(df["budget_tier"], categories=TIER_ORDER, ordered=True)
    df["performance"] = pd.Categorical(df["performance"], categories=PERF_ORDER, ordered=True)
    df["genre_list"] = df["genres"].fillna("").apply(lambda s: [g for g in s.split(", ") if g])
    return df


FILMS = load_films()
ALL_GENRES = sorted({g for gl in FILMS["genre_list"] for g in gl})
ALL_DECADES = sorted(FILMS["decade"].dropna().unique())
YEAR_MIN, YEAR_MAX = int(FILMS["release_year"].min()), int(FILMS["release_year"].max())
# Film-picker options (value = film_id), sorted by popularity-ish (vote_count).
PICKER_OPTS = [{"label": f"{r.title} ({r.release_year})", "value": int(r.film_id)}
               for r in FILMS.sort_values("vote_count", ascending=False).itertuples()]
# Marquee films — highest grossers, so the spotlight and the compare tab both open on
# something instantly recognizable instead of empty prompts.
_BY_REVENUE = FILMS.sort_values("revenue", ascending=False)
MARQUEE = _BY_REVENUE.iloc[0]
MARQUEE2 = _BY_REVENUE.iloc[1]

# ---- movie posters (TMDB), cached by imdb_id ----------------------------------
# Demo-safe: popular films are pre-cached to data/posters.json (instant + works
# offline); a miss fetches once from TMDB with a short timeout and falls back to a
# placeholder. Never a live dependency that can break the demo.
TMDB_TOKEN = os.environ.get("TMDB_READ_ACCESS_TOKEN", "")
POSTERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "posters.json")
POSTER_BASE = "https://image.tmdb.org/t/p/w342"
try:
    with open(POSTERS_FILE, encoding="utf-8") as _pf:
        POSTERS = json.load(_pf)          # {imdb_id: "/poster_path.jpg" or null}
except Exception:
    POSTERS = {}


def poster_url(imdb_id):
    if not imdb_id or not isinstance(imdb_id, str):
        return None
    if imdb_id not in POSTERS:            # cache miss → fetch once (incl. None)
        path = None
        if TMDB_TOKEN:
            try:
                r = requests.get(f"https://api.themoviedb.org/3/find/{imdb_id}",
                                 params={"external_source": "imdb_id"},
                                 headers={"Authorization": f"Bearer {TMDB_TOKEN}"}, timeout=4)
                path = (r.json().get("movie_results") or [{}])[0].get("poster_path")
            except Exception:
                path = None
        POSTERS[imdb_id] = path
        try:
            with open(POSTERS_FILE, "w", encoding="utf-8") as _pf:
                json.dump(POSTERS, _pf)
        except Exception:
            pass
    p = POSTERS.get(imdb_id)
    return (POSTER_BASE + p) if p else None


# ===========================================================================
# Filtering + aggregation
# ===========================================================================
def apply_filters(df, genres, decades, tiers, year_range):
    out = df
    if year_range:
        out = out[out["release_year"].between(year_range[0], year_range[1])]
    if decades:
        out = out[out["decade"].isin(decades)]
    if tiers:
        out = out[out["budget_tier"].isin(tiers)]
    if genres:
        sel = set(genres)
        out = out[out["genre_list"].apply(lambda gl: bool(sel.intersection(gl)))]
    return out


def genre_rollup(df, genres):
    ex = df.explode("genre_list").rename(columns={"genre_list": "genre"})
    ex = ex[ex["genre"].astype(bool)]
    if genres:
        ex = ex[ex["genre"].isin(genres)]
    g = (ex.groupby("genre")
           .agg(films=("film_id", "nunique"), avg_rating=("vote_average", "mean"),
                median_roi_pct=("roi_pct", "median")).reset_index())
    return g[g["films"] >= 5].sort_values("median_roi_pct", ascending=False)


def style(fig, title, height=430):
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=INK, family=HEAD_FONT), x=0.01, xanchor="left"),
        template="plotly_dark", font=dict(family=FONT, color=MUTED, size=12),
        height=height, margin=dict(l=55, r=20, t=50, b=45),
        legend=dict(font=dict(size=11, color=INK), bgcolor="rgba(0,0,0,0)"),
        colorway=PALETTE, paper_bgcolor=PANEL, plot_bgcolor=PANEL,
        hoverlabel=dict(font=dict(family=FONT), bgcolor=PANEL_HI, bordercolor=BORDER))
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID)
    fig.update_traces(marker_cornerradius=5, selector=dict(type="bar"))  # softer, designed bars
    return fig


# ===========================================================================
# Figures (neutral, exploratory framing — click a point to open a film)
# ===========================================================================
def fig_scatter(df):
    d = df[(df["budget"] >= 100000) & (df["revenue_multiple"] <= 25)]
    fig = px.scatter(
        d, x="vote_average", y="revenue_multiple", color="budget_tier",
        category_orders={"budget_tier": TIER_ORDER}, hover_name="title",
        custom_data=["film_id"],
        hover_data={"release_year": True, "roi_pct": ":.0f", "budget_tier": False,
                    "vote_average": ":.1f", "revenue_multiple": ":.1f"},
        labels={"vote_average": "Audience rating (/10)",
                "revenue_multiple": "Revenue multiple (× budget)", "budget_tier": "Budget tier"},
        opacity=0.5)
    fig.update_traces(marker=dict(size=6, line=dict(width=0)))
    return style(fig, "Ratings vs. returns — each point is a film (click one to open it)")


def fig_rating_band(df):
    d = df.copy()
    d["band"] = pd.cut(d["vote_average"], [0, 5, 6, 7, 8, 10],
                       labels=["Under 5", "5–6", "6–7", "7–8", "8+"])
    b = (d.groupby("band", observed=True)
           .agg(roi=("roi_pct", "median"), n=("film_id", "count")).reset_index())
    fig = px.bar(b, x="band", y="roi", text="roi",
                 color="roi", color_continuous_scale=[RED, GOLD, TEAL],
                 labels={"band": "Audience rating", "roi": "Median ROI %"})
    fig.update_traces(texttemplate="%{text:.0f}%", textposition="outside")
    fig.update_layout(coloraxis_showscale=False)
    fig.add_hline(y=0, line_color=MUTED, line_width=1)
    return style(fig, "Typical return by audience-rating band", height=430)


def fig_genre_bar(g):
    gg = g.sort_values("median_roi_pct")
    fig = px.bar(gg, x="median_roi_pct", y="genre", orientation="h", color="median_roi_pct",
                 color_continuous_scale=[RED, GOLD, TEAL],
                 labels={"median_roi_pct": "Median ROI %", "genre": ""})
    fig.update_layout(coloraxis_showscale=False)
    return style(fig, "Median return by genre", height=470)


def fig_tier_bars(df):
    t = (df.groupby("budget_tier", observed=True)
           .agg(rating=("vote_average", "mean"), roi=("roi_pct", "median"))
           .reindex(TIER_ORDER).reset_index())
    fig = make_subplots(rows=1, cols=2, subplot_titles=("Avg rating (/10)", "Median ROI %"),
                        horizontal_spacing=0.12)
    fig.add_trace(go.Bar(x=t["budget_tier"], y=t["rating"], marker_color=PALETTE[0],
                         showlegend=False), row=1, col=1)
    fig.add_trace(go.Bar(x=t["budget_tier"], y=t["roi"], marker_color=PALETTE[2],
                         showlegend=False), row=1, col=2)
    fig.update_xaxes(tickangle=-18, tickfont=dict(size=9), gridcolor=GRID)
    fig.update_yaxes(gridcolor=GRID)
    return style(fig, "Ratings & returns by budget tier", height=430)


def fig_perf_donut(df):
    p = df["performance"].value_counts().reindex(PERF_ORDER).reset_index()
    p.columns = ["performance", "count"]
    fig = px.pie(p, names="performance", values="count", hole=0.58, color="performance",
                 color_discrete_map=PERF_COLORS, category_orders={"performance": PERF_ORDER})
    fig.update_traces(textinfo="percent", textfont=dict(color="white", size=12),
                      marker=dict(line=dict(color="white", width=2)))
    fig.update_layout(legend=dict(orientation="h", y=-0.05, x=0.5, xanchor="center"))
    return style(fig, "Hit / profitable / flop mix", height=430)


def fig_leaderboard(df, value_col, title, *, n=10, largest=True, money_fmt=True,
                    suffix="", color=PALETTE[0], min_budget=None, height=430):
    """Horizontal 'top N films' bar — the crowd-pleaser view. Each bar carries its
    film_id in customdata so a click opens that film in the spotlight."""
    d = df if min_budget is None else df[df["budget"] >= min_budget]
    d = d.nlargest(n, value_col) if largest else d.nsmallest(n, value_col)
    d = d.sort_values(value_col, ascending=True)  # #1 ends up at the top of the axis
    if d.empty:
        return style(go.Figure(), title, height=height)
    text = d[value_col].map(money) if money_fmt else d[value_col].map(lambda v: f"{v:,.1f}{suffix}")
    short = [t if len(t) <= 26 else t[:25] + "…" for t in d["title"]]  # keep long titles off the bars
    # Negative (loss) bars grow leftward toward the axis labels, so anchor their value
    # labels INSIDE at the zero end (white text); positive bars label outside on the right.
    negative = bool((d[value_col] < 0).any())
    fig = go.Figure(go.Bar(
        x=d[value_col], y=d["title"], orientation="h", marker_color=color,
        customdata=d["film_id"], text=text,
        textposition="inside" if negative else "outside", insidetextanchor="start",
        textfont=dict(color="white" if negative else INK, size=11), cliponaxis=False,
        hovertext=[f"{t} ({int(y)}) · ⭐ {r:.1f}" for t, y, r
                   in zip(d["title"], d["release_year"], d["vote_average"])],
        hoverinfo="text"))
    fig.update_yaxes(tickmode="array", tickvals=list(d["title"]), ticktext=short,
                     tickfont=dict(size=10), automargin=True)
    fig.update_xaxes(showticklabels=False, showgrid=False, zeroline=False)
    lo, hi = min(0, d[value_col].min()), max(0, d[value_col].max())
    pad = (hi - lo) * 0.18 or 1
    fig.update_xaxes(range=[lo - pad * 0.2, hi + pad])
    return style(fig, title, height=height)


# ===========================================================================
# Film spotlight (the core "look up a specific film" feature)
# ===========================================================================
def money(v):
    v = float(v)
    sign, a = ("-" if v < 0 else ""), abs(v)
    if a >= 1e9:
        return f"{sign}${a/1e9:.2f}B"
    return f"{sign}${a/1e6:.1f}M"


def stat(label, value, color=INK):
    return html.Div([
        html.Div(label, className="text-uppercase",
                 style={"fontSize": "0.66rem", "letterSpacing": "0.5px", "color": MUTED,
                        "fontWeight": 600}),
        html.Div(value, style={"fontSize": "1.15rem", "fontWeight": 700, "color": color}),
    ], className="px-1")


# ===========================================================================
# Compare two films (head-to-head)
# ===========================================================================
def fig_compare(a, b):
    metrics = ["Budget", "Revenue", "Profit"]
    fig = go.Figure()
    for film, colr in ((a, GOLD), (b, TEAL)):
        vals = [film["budget"], film["revenue"], film["profit"]]
        fig.add_trace(go.Bar(
            name=film["title"][:28], x=metrics, y=vals, marker_color=colr,
            text=[money(v) for v in vals], textposition="outside",
            textfont=dict(size=11), cliponaxis=False))
    fig.update_layout(barmode="group", legend=dict(orientation="h", y=1.16, x=1,
                                                    xanchor="right", yanchor="top"),
                      bargap=0.32, bargroupgap=0.12)
    fig.update_yaxes(showticklabels=False, showgrid=False, zeroline=True, zerolinecolor=GRID)
    fig.update_xaxes(tickfont=dict(size=12, color=INK))
    return style(fig, "Budget · Revenue · Profit", height=420)


def _cmp_cell(text, win):
    return html.Td(text, style={
        "padding": "9px 12px", "textAlign": "right", "fontVariantNumeric": "tabular-nums",
        "fontWeight": 700 if win else 500, "color": TEAL if win else INK,
        "borderBottom": f"1px solid {BORDER}"})


def compare_stats(a, b):
    rt = lambda r: f"{int(r['runtime'])} min" if pd.notna(r["runtime"]) else "—"
    rows = [  # (label, a-text, b-text, a-value, b-value, higher-is-better)
        ("Audience rating", f"{a['vote_average']:.1f}", f"{b['vote_average']:.1f}",
         a["vote_average"], b["vote_average"]),
        ("Return (× budget)", f"{a['revenue_multiple']:.1f}×", f"{b['revenue_multiple']:.1f}×",
         a["revenue_multiple"], b["revenue_multiple"]),
        ("ROI", f"{a['roi_pct']:.0f}%", f"{b['roi_pct']:.0f}%", a["roi_pct"], b["roi_pct"]),
        ("Profit", money(a["profit"]), money(b["profit"]), a["profit"], b["profit"]),
        ("Votes", f"{int(a['vote_count']):,}", f"{int(b['vote_count']):,}",
         a["vote_count"], b["vote_count"]),
        ("Runtime", rt(a), rt(b), 0, 0),
    ]
    head = html.Tr([
        html.Th("", style={"padding": "9px 12px", "borderBottom": f"2px solid {ACCENT}"}),
        html.Th(a["title"], style={"padding": "9px 12px", "textAlign": "right", "color": ACCENT,
                                   "fontSize": "0.84rem", "borderBottom": f"2px solid {ACCENT}"}),
        html.Th(b["title"], style={"padding": "9px 12px", "textAlign": "right", "color": TEAL,
                                   "fontSize": "0.84rem", "borderBottom": f"2px solid {TEAL}"}),
    ])
    body = []
    for label, at, bt, av, bv in rows:
        body.append(html.Tr([
            html.Td(label, style={"padding": "9px 12px", "color": MUTED, "fontSize": "0.82rem",
                                  "textTransform": "uppercase", "letterSpacing": "0.4px",
                                  "borderBottom": f"1px solid {BORDER}"}),
            _cmp_cell(at, av > bv), _cmp_cell(bt, bv > av),
        ]))
    return html.Table([html.Thead(head), html.Tbody(body)],
                      style={"width": "100%", "borderCollapse": "collapse"})


COMPARE_PROMPT = html.Div("Pick a film on each side to compare them.",
                          className="text-muted py-3", style={"fontSize": "0.9rem"})


# ===========================================================================
# Film page — the rich single-film view (poster + money + how-it-ranks + scatter)
# ===========================================================================
def _pct(series, value):
    """Percentile of `value` within `series` (share of films it beats)."""
    s = series.dropna()
    if len(s) == 0 or pd.isna(value):
        return 0.0
    return float((s < value).mean() * 100)


def fig_money(row):
    labels = ["Budget", "Revenue", "Profit"]
    vals = [row["budget"], row["revenue"], row["profit"]]
    colors = [MUTED, GOLD, TEAL if row["profit"] >= 0 else RED]
    fig = go.Figure(go.Bar(
        x=vals, y=labels, orientation="h", marker_color=colors,
        text=[money(v) for v in vals], textposition="outside",
        textfont=dict(size=12, color=INK), cliponaxis=False, showlegend=False))
    fig.update_yaxes(autorange="reversed", tickfont=dict(size=11, color=INK))
    fig.update_xaxes(showticklabels=False, showgrid=False, zeroline=True, zerolinecolor=GRID)
    fig.update_xaxes(range=[min(0, min(vals)) * 1.05, max(vals) * 1.28])
    return style(fig, "The money", height=235)


def fig_ranks(row):
    items = [("Revenue", _pct(FILMS["revenue"], row["revenue"]), GOLD),
             ("ROI", _pct(FILMS["roi_pct"], row["roi_pct"]), ORANGE),
             ("Rating", _pct(FILMS["vote_average"], row["vote_average"]), TEAL)]
    pcts = [i[1] for i in items]

    def lab(p):
        return f"top {max(1, round(100 - p))}%" if p >= 50 else f"beats {round(p)}%"
    fig = go.Figure(go.Bar(
        x=pcts, y=[i[0] for i in items], orientation="h",
        marker_color=[i[2] for i in items],
        text=[lab(p) for p in pcts], textposition="outside",
        textfont=dict(size=11, color=INK), cliponaxis=False, showlegend=False))
    fig.update_yaxes(autorange="reversed", tickfont=dict(size=11, color=INK))
    fig.update_xaxes(range=[0, 122], showticklabels=False, showgrid=False, zeroline=False)
    return style(fig, "How it ranks vs. all films", height=235)


def fig_film_scatter(row):
    d = FILMS[(FILMS["budget"] >= 100000) & (FILMS["revenue_multiple"] <= 25)]
    fig = go.Figure()
    fig.add_trace(go.Scattergl(
        x=d["vote_average"], y=d["revenue_multiple"], mode="markers",
        marker=dict(size=4, color=MUTED, opacity=0.18), hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(
        x=[row["vote_average"]], y=[min(row["revenue_multiple"], 25)], mode="markers",
        marker=dict(size=16, color=GOLD, line=dict(color="white", width=2)),
        hovertext=[row["title"]], hoverinfo="text", showlegend=False))
    fig.update_xaxes(title_text="Rating (/10)", title_font=dict(size=11))
    fig.update_yaxes(title_text="Return (× budget)", title_font=dict(size=11))
    return style(fig, "Where it sits", height=235)


def poster_block(row):
    url = poster_url(row.get("imdb_id"))
    if url:
        return html.Img(src=url, alt=row["title"],
                        style={"width": "100%", "borderRadius": "8px",
                               "border": f"1px solid {BORDER}", "boxShadow": SHADOW,
                               "display": "block"})
    return html.Div(row["title"],
                    style={"width": "100%", "aspectRatio": "2 / 3", "borderRadius": "8px",
                           "border": f"1px dashed {BORDER}", "backgroundColor": PANEL_HI,
                           "color": MUTED, "fontSize": "0.82rem", "textAlign": "center",
                           "display": "flex", "alignItems": "center",
                           "justifyContent": "center", "padding": "0 10px"})


def film_meta(row):
    perf_color = PERF_COLORS.get(row["performance"], MUTED)
    badge_text = "#15120C" if perf_color == GOLD else "white"
    rt = f"{int(row['runtime'])} min" if pd.notna(row["runtime"]) else "—"
    return html.Div([
        html.Span(row["title"], style={"fontFamily": HEAD_FONT, "fontWeight": 600,
                                       "fontSize": "1.45rem", "color": INK, "letterSpacing": "0.3px"}),
        html.Span(f"  ({int(row['release_year'])})", style={"color": MUTED, "fontSize": "1rem"}),
        html.Div(row["genres"] or "—", style={"fontSize": "0.85rem", "color": "#CBC1AC",
                                              "margin": "2px 0 8px"}),
        html.Span(PERF_BADGE.get(row["performance"], row["performance"]),
                  title="Performance tier = revenue ÷ production budget",
                  style={"display": "inline-block", "backgroundColor": perf_color, "color": badge_text,
                         "fontWeight": 700, "fontSize": "0.8rem", "padding": "0.35em 0.75em",
                         "borderRadius": "6px"}),
        dbc.Row([
            dbc.Col(stat("Rating", f"{row['vote_average']:.1f}/10"), xs=6, sm=3),
            dbc.Col(stat("Return", f"{row['revenue_multiple']:.1f}×"), xs=6, sm=3),
            dbc.Col(stat("ROI", f"{row['roi_pct']:.0f}%"), xs=6, sm=3),
            dbc.Col(stat("Runtime", rt), xs=6, sm=3),
        ], className="g-2 mt-2"),
    ])


# ===========================================================================
# UI helpers
# ===========================================================================
def kpi(title, idd, accent=ACCENT, tip=None):
    """Metric tile with depth (soft shadow) and a single cohesive accent — a coloured top
    rule + coloured value, same hue family across all tiles (branded, not the old rainbow).
    `tip` adds a hover tooltip explaining the metric."""
    return dbc.Card(dbc.CardBody([
        html.Div(title, className="text-uppercase", title=tip,
                 style={"fontSize": "0.68rem", "letterSpacing": "0.7px", "color": MUTED,
                        "fontWeight": 600, "cursor": "help" if tip else "default"}),
        html.Div(id=idd, style={"fontSize": "1.55rem", "fontWeight": 700, "color": accent,
                                "lineHeight": "1.15", "marginTop": "4px"}),
    ], style={"padding": "0.85rem 1rem"}), className="h-100",
        style={"border": f"1px solid {BORDER}", "borderTop": f"3px solid {accent}",
               "borderRadius": "8px", "backgroundColor": PANEL, "boxShadow": SHADOW})


def dd(idd, options, placeholder):
    return dcc.Dropdown(id=idd, multi=True, placeholder=placeholder,
                        options=[{"label": o, "value": o} for o in options])


def graph(idd, height="44vh", minh="360px"):
    return dcc.Graph(id=idd, style={"height": height, "minHeight": minh},
                     config={"displayModeBar": False, "responsive": True})


def card(body, **kw):
    return dbc.Card(dbc.CardBody(body),
                    style={"border": f"1px solid {BORDER}", "borderRadius": "8px",
                           "backgroundColor": PANEL, "boxShadow": SHADOW, **kw})


TABLE_COLS = [
    {"name": "Title", "id": "title"},
    {"name": "Year", "id": "release_year"},
    {"name": "Genres", "id": "genres"},
    {"name": "Budget", "id": "budget", "type": "numeric", "format": {"specifier": "$,.0f"}},
    {"name": "Revenue", "id": "revenue", "type": "numeric", "format": {"specifier": "$,.0f"}},
    {"name": "Profit", "id": "profit", "type": "numeric", "format": {"specifier": "$,.0f"}},
    {"name": "Multiple", "id": "revenue_multiple", "type": "numeric", "format": {"specifier": ".1f"}},
    {"name": "ROI %", "id": "roi_pct", "type": "numeric", "format": {"specifier": ".0f"}},
    {"name": "Rating", "id": "vote_average", "type": "numeric", "format": {"specifier": ".1f"}},
]


# ===========================================================================
# App
# ===========================================================================
app = Dash(__name__, external_stylesheets=[dbc.themes.FLATLY], title="Box Office vs. Ratings")
server = app.server

# Dark "movie theater" theming for the bits Python styles can't reach: the condensed
# title font, and the Dash 3 native dropdown / slider / tabs / table-filter controls.
app.index_string = """<!DOCTYPE html>
<html>
<head>
{%metas%}<title>Box Office vs. Ratings</title>{%favicon%}{%css%}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@500;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  html, body { background:#15120C; color:#ECE4D3; }
  ::selection { background:#D9A441; color:#15120C; }
  /* Dropdown (Dash 3 native) */
  .dash-dropdown, .dash-dropdown-trigger { background:#1F1A12 !important; border-color:#352D20 !important;
      color:#ECE4D3 !important; border-radius:6px; }
  .dash-dropdown-value, .dash-dropdown-value-item span, .dash-dropdown-placeholder { color:#ECE4D3 !important; }
  /* open menu popup */
  .dash-dropdown-content { background:#1F1A12 !important; color:#ECE4D3 !important;
      border:1px solid #352D20 !important; }
  .dash-dropdown-search { background:#15120C !important; color:#ECE4D3 !important;
      border:1px solid #352D20 !important; }
  .dash-options-list, .dash-dropdown-options { background:#1F1A12 !important; color:#ECE4D3 !important; }
  .dash-options-list-option, .dash-dropdown-option { color:#ECE4D3 !important; background:transparent !important; }
  .dash-options-list-option:hover, .dash-dropdown-option:hover { background:#2A2318 !important;
      color:#D9A441 !important; }
  .dash-dropdown-action-button { color:#D9A441 !important; background:transparent !important; }
  /* Range slider (Dash 3 native) */
  .dash-slider-track { background:#352D20 !important; }
  .dash-slider-range { background:#D9A441 !important; }
  .dash-slider-handle { background:#D9A441 !important; border-color:#D9A441 !important; }
  .dash-slider-mark-text { color:#A99E88 !important; }
  .dash-range-slider-input { background:#1F1A12 !important; color:#ECE4D3 !important; border-color:#352D20 !important; }
  /* Tabs */
  .nav-tabs { border-bottom:1px solid #352D20 !important; }
  .nav-tabs .nav-link { color:#A99E88 !important; border:none !important; font-weight:500; }
  .nav-tabs .nav-link:hover { color:#ECE4D3 !important; }
  .nav-tabs .nav-link.active { color:#D9A441 !important; background:transparent !important;
      border-bottom:2px solid #D9A441 !important; }
  /* Table filter inputs */
  .dash-table-container input { color:#ECE4D3 !important; }
  .dash-filter input::placeholder { color:#8A8068 !important; }
</style>
</head>
<body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body>
</html>"""

app.layout = dbc.Container(fluid=True, className="px-4 py-3",
                           style={"backgroundColor": PAGE_BG, "fontFamily": FONT,
                                  "minHeight": "100vh"}, children=[

    # ---- header (movie-marquee: gold accent rule + condensed title on dark) ----
    html.Div(dbc.Row([
        dbc.Col([
            html.Div("BOX OFFICE vs. RATINGS",
                     style={"color": INK, "fontFamily": HEAD_FONT, "fontWeight": 600,
                            "fontSize": "1.9rem", "letterSpacing": "1.5px", "lineHeight": "1.1"}),
            html.Div(style={"height": "3px", "width": "70px", "background": GOLD,
                            "margin": "7px 0 9px"}),
            html.P(f"Do better films make more money? {len(FILMS):,} films, 2000–2026.  "
                   f"·  {DATA_SOURCE} · TMDB",
                   className="mb-0", style={"fontSize": "0.86rem", "color": MUTED}),
        ], md=9, className="d-flex flex-column justify-content-center"),
        dbc.Col(dbc.Button("↻ Refresh data", id="refresh", color="warning", outline=True,
                           size="sm", className="float-end"), md=3,
                className="d-flex align-items-center justify-content-end"),
    ], className="align-items-center g-0"),
        style={"background": PANEL, "border": f"1px solid {BORDER}", "borderRadius": "10px",
               "padding": "1.15rem 1.4rem", "marginBottom": "1.1rem", "boxShadow": SHADOW}),

    # ---- film page (search a movie → poster + money + how-it-ranks + scatter) ----
    card([
        dbc.Row([
            dbc.Col(html.Small("SPOTLIGHT A FILM", className="fw-bold",
                               style={"color": MUTED, "letterSpacing": "0.6px"}), md=5),
            dbc.Col(dcc.Dropdown(id="film-picker", options=PICKER_OPTS,
                                 value=int(MARQUEE["film_id"]),
                                 placeholder="Search any film by name…", optionHeight=34), md=7),
        ], className="g-2 align-items-center mb-3"),
        dbc.Row([
            dbc.Col(html.Div(poster_block(MARQUEE), id="film-poster"), xs=4, md=3, lg=2),
            dbc.Col([
                html.Div(film_meta(MARQUEE), id="film-meta"),
                dbc.Row([
                    dbc.Col(graph("g-film-money", "22vh", "175px"), md=4),
                    dbc.Col(graph("g-film-ranks", "22vh", "175px"), md=4),
                    dbc.Col(graph("g-film-scatter", "22vh", "175px"), md=4),
                ], className="g-2 mt-1"),
            ], xs=8, md=9, lg=10),
        ], className="g-3"),
    ], marginBottom="1rem"),

    # ---- KPI cards (summarise the current filter) ----
    dbc.Row([
        dbc.Col(kpi("Films shown", "kpi-films", GOLD), md=2, xs=6),
        dbc.Col(kpi("Avg rating", "kpi-rating", TEAL,
                    tip="Average audience rating (out of 10)."), md=2, xs=6),
        dbc.Col(kpi("Median return", "kpi-mult", ORANGE,
                    tip="Typical revenue as a multiple of budget (e.g. 1.7× = $1.70 back per $1)."),
                md=2, xs=6),
        dbc.Col(kpi("Total box office", "kpi-box", GOLD,
                    tip="Combined worldwide revenue of all films in the current selection."),
                md=2, xs=6),
        dbc.Col(kpi("Total profit", "kpi-profit", TEAL,
                    tip="Combined revenue minus combined budget."), md=2, xs=6),
        dbc.Col(kpi("Hits (2×+)", "kpi-hits", ORANGE,
                    tip="Share of films that earned at least 2× their budget back."), md=2, xs=6),
    ], className="g-2 my-3"),

    # ---- filters ----
    card(dbc.Row([
        dbc.Col([html.Small("GENRE", className="fw-bold", style={"color": MUTED}),
                 dd("f-genre", ALL_GENRES, "All genres")], md=3),
        dbc.Col([html.Small("DECADE", className="fw-bold", style={"color": MUTED}),
                 dd("f-decade", ALL_DECADES, "All decades")], md=2),
        dbc.Col([html.Small("BUDGET TIER", className="fw-bold", style={"color": MUTED}),
                 dd("f-tier", TIER_ORDER, "All tiers")], md=3),
        dbc.Col([html.Small("RELEASE-YEAR RANGE", className="fw-bold", style={"color": MUTED}),
                 dcc.RangeSlider(id="f-year", min=YEAR_MIN, max=YEAR_MAX, step=1,
                                 value=[YEAR_MIN, YEAR_MAX],
                                 marks={y: str(y) for y in range(YEAR_MIN, YEAR_MAX + 1, 5)},
                                 tooltip={"placement": "bottom"})], md=4),
    ], className="g-3 align-items-start")),

    # ---- tabs ----
    html.Div(card(dbc.Tabs(active_tab="t-top", children=[
        dbc.Tab(label="Top films", tab_id="t-top", children=[
            html.P("Biggest winners and losers in the current selection. Click a bar to open a film.",
                   className="mt-2 mb-2", style={"fontSize": "0.82rem", "color": MUTED}),
            dbc.Row([
                dbc.Col(graph("g-top-rev", "42vh"), lg=6),
                dbc.Col(graph("g-top-profit", "42vh"), lg=6),
            ], className="g-3"),
            dbc.Row([
                dbc.Col(graph("g-top-mult", "42vh"), lg=6),
                dbc.Col(graph("g-top-loss", "42vh"), lg=6),
            ], className="g-3 mt-0"),
        ]),
        dbc.Tab(label="Compare films", tab_id="t-compare", children=[
            html.P("Pick any two films to see their money and ratings head-to-head — "
                   "the better value in each row is highlighted.",
                   className="mt-2 mb-2", style={"fontSize": "0.82rem", "color": MUTED}),
            dbc.Row([
                dbc.Col([html.Small("FILM A", className="fw-bold", style={"color": ACCENT}),
                         dcc.Dropdown(id="cmp-a", options=PICKER_OPTS,
                                      value=int(MARQUEE["film_id"]), optionHeight=34,
                                      placeholder="Choose a film…")], md=6),
                dbc.Col([html.Small("FILM B", className="fw-bold", style={"color": TEAL}),
                         dcc.Dropdown(id="cmp-b", options=PICKER_OPTS,
                                      value=int(MARQUEE2["film_id"]), optionHeight=34,
                                      placeholder="Choose a film…")], md=6),
            ], className="g-3"),
            dbc.Row([
                dbc.Col(graph("g-compare", "44vh"), lg=7),
                dbc.Col(html.Div(id="compare-stats", className="mt-4 mt-lg-0"), lg=5),
            ], className="g-3 mt-1 align-items-center"),
        ]),
        dbc.Tab(label="Browse films", tab_id="t-browse", children=[
            html.P("Search any column, sort by a header, or click a row to open a film.",
                   className="mt-2 mb-2", style={"fontSize": "0.82rem", "color": MUTED}),
            dash_table.DataTable(
                id="film-table", columns=TABLE_COLS, sort_action="native",
                filter_action="native", page_size=12, page_action="native",
                cell_selectable=True, style_as_list_view=True,
                style_header={"backgroundColor": PANEL_HI, "color": GOLD, "fontWeight": "600",
                              "border": "none", "borderBottom": f"1px solid {BORDER}",
                              "fontSize": "0.8rem", "textTransform": "uppercase"},
                style_cell={"fontFamily": FONT, "fontSize": "0.82rem", "padding": "7px 10px",
                            "textAlign": "left", "maxWidth": 230, "overflow": "hidden",
                            "textOverflow": "ellipsis", "border": "none", "color": INK,
                            "backgroundColor": PANEL,
                            "borderBottom": f"1px solid {BORDER}", "cursor": "pointer"},
                style_data_conditional=[{"if": {"row_index": "odd"}, "backgroundColor": "#221C12"},
                                        {"if": {"state": "active"},
                                         "backgroundColor": PANEL_HI, "border": f"1px solid {GOLD}"}],
                style_filter={"backgroundColor": PANEL_HI, "color": INK}),
        ]),
        dbc.Tab(label="Ratings vs. returns", tab_id="t-rr", children=[
            html.P("The core question: does a higher audience rating mean a bigger return? "
                   "Each point is a film — click one to open it.",
                   className="mt-2 mb-2", style={"fontSize": "0.82rem", "color": MUTED}),
            dbc.Row([dbc.Col(graph("g-scatter"), lg=7), dbc.Col(graph("g-band"), lg=5)],
                    className="g-3")]),
        dbc.Tab(label="What makes money", tab_id="t-money", children=[
            html.P("Which genres and budget levels actually make money — and the overall "
                   "hit / flop split.",
                   className="mt-2 mb-2", style={"fontSize": "0.82rem", "color": MUTED}),
            dbc.Row([
                dbc.Col(graph("g-genre-bar", "50vh"), lg=5),
                dbc.Col(graph("g-tier", "50vh"), lg=4),
                dbc.Col(graph("g-perf", "50vh"), lg=3),
            ], className="g-3")]),
    ])), className="mt-3"),

    html.P("Built with Dash + Plotly on PostgreSQL · data from TMDB. This product uses the "
           "TMDB API but is not endorsed or certified by TMDB.",
           className="text-center mt-3 mb-1", style={"fontSize": "0.74rem", "color": "#8A8068"}),
])


# ===========================================================================
# Callbacks
# ===========================================================================
@app.callback(
    Output("kpi-films", "children"), Output("kpi-rating", "children"),
    Output("kpi-mult", "children"), Output("kpi-box", "children"),
    Output("kpi-profit", "children"), Output("kpi-hits", "children"),
    Output("g-scatter", "figure"), Output("g-band", "figure"),
    Output("g-genre-bar", "figure"),
    Output("g-tier", "figure"), Output("g-perf", "figure"),
    Output("g-top-rev", "figure"), Output("g-top-profit", "figure"),
    Output("g-top-mult", "figure"), Output("g-top-loss", "figure"),
    Output("film-table", "data"),
    Input("f-genre", "value"), Input("f-decade", "value"),
    Input("f-tier", "value"), Input("f-year", "value"),
)
def update(genres, decades, tiers, year_range):
    df = apply_filters(FILMS, genres, decades, tiers, year_range)
    if df.empty:
        e = style(go.Figure(), "No films match the current filters")
        return ("0", "—", "—", "$0", "$0", "—", e, e, e, e, e, e, e, e, e, [])

    profit_txt = money(df["profit"].sum())
    box_txt = money(df["revenue"].sum())
    hits = (df["performance"] == "Hit (>=2x)").mean() * 100
    g = genre_rollup(df, genres)
    table = (df.sort_values("profit", ascending=False)
               [["film_id", "title", "release_year", "genres", "budget", "revenue",
                 "profit", "revenue_multiple", "roi_pct", "vote_average"]].to_dict("records"))

    return (
        f"{len(df):,}", f"{df['vote_average'].mean():.2f}",
        f"{df['revenue_multiple'].median():.1f}×", box_txt,
        profit_txt, f"{hits:.0f}%",
        fig_scatter(df), fig_rating_band(df), fig_genre_bar(g),
        fig_tier_bars(df), fig_perf_donut(df),
        fig_leaderboard(df, "revenue", "Biggest box office", color=GOLD),
        fig_leaderboard(df, "profit", "Biggest profit", color=TEAL),
        fig_leaderboard(df, "revenue_multiple", "Best return on budget (budget ≥ $10M)",
                        money_fmt=False, suffix="×", color=ORANGE, min_budget=10_000_000),
        fig_leaderboard(df, "profit", "Biggest losses", largest=False, color=RED),
        table,
    )


CLICK_GRAPHS = ["g-scatter", "g-top-rev", "g-top-profit", "g-top-mult", "g-top-loss"]


def _film_id_from_click(click):
    """customdata is a list ([film_id]) for px scatter, a scalar for go.Bar."""
    if not click or not click.get("points"):
        return None
    cd = click["points"][0].get("customdata")
    return (cd[0] if isinstance(cd, (list, tuple)) else cd)


@app.callback(
    Output("film-poster", "children"), Output("film-meta", "children"),
    Output("g-film-money", "figure"), Output("g-film-ranks", "figure"),
    Output("g-film-scatter", "figure"), Output("film-picker", "value"),
    Input("film-picker", "value"),
    *[Input(g, "clickData") for g in CLICK_GRAPHS],
    Input("film-table", "active_cell"),
    State("film-table", "derived_viewport_data"),
)
def spotlight(picker_id, *args):
    *clicks, cell, viewport = args
    trig = callback_context.triggered_id
    fid = None
    # trig is None on the initial page load — render the pre-selected marquee film.
    if trig in (None, "film-picker"):
        fid = picker_id
    elif trig in CLICK_GRAPHS:
        fid = _film_id_from_click(clicks[CLICK_GRAPHS.index(trig)])
    elif trig == "film-table" and cell and viewport:
        fid = (viewport[cell["row"]] or {}).get("film_id")
    try:
        fid = int(fid) if fid is not None else None
    except (TypeError, ValueError):
        fid = None
    row = FILMS[FILMS["film_id"] == fid] if fid is not None else FILMS.iloc[0:0]
    if row.empty:  # nothing valid selected — leave the current film page as-is
        return (no_update,) * 6
    r = row.iloc[0]
    # Don't echo a value back to the picker when the picker (or initial load) is the source.
    new_value = no_update if trig in (None, "film-picker") else fid
    return (poster_block(r), film_meta(r), fig_money(r), fig_ranks(r),
            fig_film_scatter(r), new_value)


@app.callback(
    Output("g-compare", "figure"), Output("compare-stats", "children"),
    Input("cmp-a", "value"), Input("cmp-b", "value"),
)
def compare(a_id, b_id):
    if not a_id or not b_id:
        return style(go.Figure(), "Budget · Revenue · Profit", height=420), COMPARE_PROMPT
    ra = FILMS[FILMS["film_id"] == int(a_id)]
    rb = FILMS[FILMS["film_id"] == int(b_id)]
    if ra.empty or rb.empty:
        return style(go.Figure(), "Budget · Revenue · Profit", height=420), COMPARE_PROMPT
    a, b = ra.iloc[0], rb.iloc[0]
    return fig_compare(a, b), compare_stats(a, b)


@app.callback(Output("f-year", "value"), Input("refresh", "n_clicks"),
              State("f-year", "value"), prevent_initial_call=True)
def refresh_data(_n, year_range):
    """Re-pull films from PostgreSQL without a restart (live/refreshed data)."""
    global FILMS
    FILMS = load_films()
    return year_range


if __name__ == "__main__":
    app.run(debug=True, port=8050)
