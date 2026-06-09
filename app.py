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

import os

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, callback_context, dash_table, dcc, html, no_update
from dotenv import load_dotenv
from plotly.subplots import make_subplots
from sqlalchemy import create_engine, text

# ===========================================================================
# Configuration
# ===========================================================================
load_dotenv()

INK = "#1F2A37"
MUTED = "#6B7280"
GRID = "#ECEEF2"
BORDER = "#E4E7EB"      # hairline card border (replaces drop-shadows)
ACCENT = "#1F4E79"
PALETTE = ["#1F4E79", "#2E8B8B", "#C9923E", "#7D5BA6", "#B5524B", "#4A6FA5"]
FONT = "Inter, Segoe UI, Helvetica, Arial, sans-serif"

TIER_ORDER = ["Low (<$10M)", "Mid ($10-50M)", "High ($50-150M)", "Blockbuster (>=$150M)"]
PERF_ORDER = ["Flop (<1x)", "Profitable (1-2x)", "Hit (>=2x)"]
PERF_COLORS = {"Flop (<1x)": "#B5524B", "Profitable (1-2x)": "#C9923E", "Hit (>=2x)": "#2E8B8B"}

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
# Marquee film for the opening spotlight — the highest-grossing title, so the demo
# loads on something instantly recognizable instead of an empty prompt.
MARQUEE = FILMS.loc[FILMS["revenue"].idxmax()]


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
        title=dict(text=title, font=dict(size=15, color=INK, family=FONT), x=0.01, xanchor="left"),
        template="plotly_white", font=dict(family=FONT, color=MUTED, size=12),
        height=height, margin=dict(l=55, r=20, t=50, b=45),
        legend=dict(font=dict(size=11), bgcolor="rgba(0,0,0,0)"),
        colorway=PALETTE, paper_bgcolor="white", plot_bgcolor="white",
        hoverlabel=dict(font=dict(family=FONT)))
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID)
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
                 color="roi", color_continuous_scale=["#B5524B", "#C9923E", "#2E8B8B"],
                 labels={"band": "Audience rating", "roi": "Median ROI %"})
    fig.update_traces(texttemplate="%{text:.0f}%", textposition="outside")
    fig.update_layout(coloraxis_showscale=False)
    fig.add_hline(y=0, line_color=MUTED, line_width=1)
    return style(fig, "Typical return by audience-rating band", height=430)


def fig_trend(df):
    d = df[df["release_year"] <= 2025]
    yr = (d.groupby("release_year")
           .agg(rating=("vote_average", "mean"), roi=("roi_pct", "median")).reset_index())
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=yr["release_year"], y=yr["rating"], name="Avg rating",
                             mode="lines", line=dict(color=PALETTE[0], width=3)), secondary_y=False)
    fig.add_trace(go.Scatter(x=yr["release_year"], y=yr["roi"], name="Median ROI %",
                             mode="lines", line=dict(color=PALETTE[2], width=3)), secondary_y=True)
    fig.update_yaxes(title_text="Avg rating (/10)", secondary_y=False, color=PALETTE[0], gridcolor=GRID)
    fig.update_yaxes(title_text="Median ROI %", secondary_y=True, color=PALETTE[2], showgrid=False)
    fig.update_xaxes(title_text="Release year", gridcolor=GRID)
    return style(fig, "Ratings & returns over time (through 2025)")


def fig_genre_scatter(g):
    fig = px.scatter(g, x="avg_rating", y="median_roi_pct", size="films", color="genre",
                     text="genre", size_max=42,
                     labels={"avg_rating": "Avg audience rating (/10)",
                             "median_roi_pct": "Median ROI %", "genre": "Genre"})
    fig.update_traces(textposition="top center", textfont=dict(size=10, color=INK),
                      marker=dict(line=dict(width=0)))
    fig.update_layout(showlegend=False)
    return style(fig, "Genres — rating vs. return (bubble size = # films)", height=470)


def fig_genre_bar(g):
    gg = g.sort_values("median_roi_pct")
    fig = px.bar(gg, x="median_roi_pct", y="genre", orientation="h", color="median_roi_pct",
                 color_continuous_scale=["#B5524B", "#C9923E", "#2E8B8B"],
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
    fig = go.Figure(go.Bar(
        x=d[value_col], y=d["title"], orientation="h", marker_color=color,
        customdata=d["film_id"], text=text, textposition="outside", cliponaxis=False,
        hovertext=[f"{t} ({int(y)}) · ⭐ {r:.1f}" for t, y, r
                   in zip(d["title"], d["release_year"], d["vote_average"])],
        hoverinfo="text"))
    fig.update_yaxes(tickfont=dict(size=10), automargin=True)
    fig.update_xaxes(showticklabels=False, showgrid=False, zeroline=False)
    pad = (d[value_col].max() - min(0, d[value_col].min())) * 0.18 or 1
    fig.update_xaxes(range=[min(0, d[value_col].min()) - pad * 0.3, d[value_col].max() + pad])
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


def film_detail(row):
    profit_color = "#2E8B8B" if row["profit"] >= 0 else "#B5524B"
    imdb = (html.A("View on IMDb ↗", href=f"https://www.imdb.com/title/{row['imdb_id']}/",
                   target="_blank", style={"fontSize": "0.8rem"})
            if isinstance(row.get("imdb_id"), str) and row["imdb_id"] else "")
    return dbc.Row([
        dbc.Col([
            html.H5(f"{row['title']}  ", className="d-inline fw-bold", style={"color": INK}),
            html.Span(f"({int(row['release_year'])})", style={"color": MUTED}),
            html.Div(row["genres"] or "—", className="text-muted",
                     style={"fontSize": "0.85rem", "marginBottom": "2px"}),
            dbc.Badge(row["performance"], color="light", text_color="dark",
                      className="me-2", style={"border": f"1px solid {profit_color}"}),
            html.Span(imdb),
        ], md=4, className="border-end"),
        dbc.Col(dbc.Row([
            dbc.Col(stat("Budget", money(row["budget"])), xs=4),
            dbc.Col(stat("Revenue", money(row["revenue"])), xs=4),
            dbc.Col(stat("Profit", money(row["profit"]), profit_color), xs=4),
            dbc.Col(stat("Return", f"{row['revenue_multiple']:.1f}×"), xs=3),
            dbc.Col(stat("ROI", f"{row['roi_pct']:.0f}%"), xs=3),
            dbc.Col(stat("Rating", f"{row['vote_average']:.1f}/10"), xs=3),
            dbc.Col(stat("Runtime", f"{int(row['runtime'])} min" if pd.notna(row["runtime"]) else "—"), xs=3),
        ], className="g-2"), md=8),
    ], className="align-items-center")


DETAIL_PROMPT = html.Div(
    "Search a film, or click any chart point or table row, to see its budget, revenue, "
    "profit, ROI and rating.",
    className="text-muted py-2", style={"fontSize": "0.9rem"})


# ===========================================================================
# UI helpers
# ===========================================================================
def kpi(title, idd):
    """One uniform metric tile — no per-card accent colour (the rainbow look reads as a
    template). Restraint: hairline border, ink number, muted label. The data is the colour."""
    return dbc.Card(dbc.CardBody([
        html.Div(title, className="text-uppercase",
                 style={"fontSize": "0.68rem", "letterSpacing": "0.7px", "color": MUTED, "fontWeight": 600}),
        html.Div(id=idd, style={"fontSize": "1.5rem", "fontWeight": 700, "color": INK,
                                "lineHeight": "1.15", "marginTop": "4px"}),
    ], style={"padding": "0.85rem 1rem"}), className="h-100",
        style={"border": f"1px solid {BORDER}", "borderRadius": "8px", "backgroundColor": "white"})


def dd(idd, options, placeholder):
    return dcc.Dropdown(id=idd, multi=True, placeholder=placeholder,
                        options=[{"label": o, "value": o} for o in options])


def graph(idd, height="44vh"):
    return dcc.Graph(id=idd, style={"height": height, "minHeight": "360px"},
                     config={"displayModeBar": False, "responsive": True})


def card(body, **kw):
    return dbc.Card(dbc.CardBody(body),
                    style={"border": f"1px solid {BORDER}", "borderRadius": "8px",
                           "backgroundColor": "white", **kw})


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

app.layout = dbc.Container(fluid=True, className="px-4 py-3",
                           style={"backgroundColor": "#F7F8FA", "fontFamily": FONT,
                                  "minHeight": "100vh"}, children=[

    dbc.Row([
        dbc.Col([
            html.H3("Box Office vs. Ratings", className="fw-bold mb-1",
                    style={"color": INK, "letterSpacing": "-0.4px"}),
            html.Div(style={"height": "3px", "width": "54px", "background": ACCENT,
                            "borderRadius": "2px", "marginBottom": "8px"}),
            html.P(f"Explore the budgets, box-office returns and audience ratings of {len(FILMS):,} "
                   f"films (2000–2026). {DATA_SOURCE} · TMDB data.",
                   className="mb-0", style={"fontSize": "0.86rem", "color": MUTED}),
        ], md=9),
        dbc.Col(dbc.Button("Refresh data", id="refresh", color="secondary", outline=True,
                           size="sm", className="float-end mt-2"), md=3),
    ], className="mb-3 align-items-center"),

    # ---- film spotlight (search a specific movie) ----
    card([
        dbc.Row([
            dbc.Col(html.Small("SPOTLIGHT A FILM", className="fw-bold", style={"color": MUTED}), md=3),
        ]),
        dbc.Row([
            dbc.Col(dcc.Dropdown(id="film-picker", options=PICKER_OPTS,
                                 value=int(MARQUEE["film_id"]),
                                 placeholder="Search any film by name…", optionHeight=34), md=4),
            dbc.Col(html.Div(film_detail(MARQUEE), id="film-detail"), md=8),
        ], className="g-3 align-items-center"),
    ], marginBottom="1rem"),

    # ---- KPI cards (summarise the current filter) ----
    dbc.Row([
        dbc.Col(kpi("Films shown", "kpi-films"), md=2, xs=6),
        dbc.Col(kpi("Avg rating", "kpi-rating"), md=2, xs=6),
        dbc.Col(kpi("Median return", "kpi-mult"), md=2, xs=6),
        dbc.Col(kpi("Median ROI %", "kpi-roi"), md=2, xs=6),
        dbc.Col(kpi("Total profit", "kpi-profit"), md=2, xs=6),
        dbc.Col(kpi("Hit rate", "kpi-hits"), md=2, xs=6),
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
        dbc.Tab(label="Browse films", tab_id="t-browse", children=[
            html.P("Search any column, sort by a header, or click a row to open a film.",
                   className="mt-2 mb-2", style={"fontSize": "0.82rem", "color": MUTED}),
            dash_table.DataTable(
                id="film-table", columns=TABLE_COLS, sort_action="native",
                filter_action="native", page_size=12, page_action="native",
                cell_selectable=True, style_as_list_view=True,
                style_header={"backgroundColor": INK, "color": "white", "fontWeight": "600",
                              "border": "none", "fontSize": "0.8rem"},
                style_cell={"fontFamily": FONT, "fontSize": "0.82rem", "padding": "7px 10px",
                            "textAlign": "left", "maxWidth": 230, "overflow": "hidden",
                            "textOverflow": "ellipsis", "border": "none",
                            "borderBottom": "1px solid #F0F1F4", "cursor": "pointer"},
                style_data_conditional=[{"if": {"row_index": "odd"}, "backgroundColor": "#FAFBFC"}],
                style_filter={"backgroundColor": "#F3F4F6"}),
        ]),
        dbc.Tab(label="Ratings vs. returns", tab_id="t-rr", children=dbc.Row([
            dbc.Col(graph("g-scatter"), lg=7), dbc.Col(graph("g-band"), lg=5),
        ], className="g-3 mt-1")),
        dbc.Tab(label="By genre", tab_id="t-genre", children=dbc.Row([
            dbc.Col(graph("g-genre-scatter", "48vh"), lg=7),
            dbc.Col(graph("g-genre-bar", "48vh"), lg=5),
        ], className="g-3 mt-1")),
        dbc.Tab(label="By budget", tab_id="t-budget", children=dbc.Row([
            dbc.Col(graph("g-tier"), lg=8), dbc.Col(graph("g-perf"), lg=4),
        ], className="g-3 mt-1")),
        dbc.Tab(label="Over time", tab_id="t-time", children=dbc.Row([
            dbc.Col(graph("g-trend"), lg=12),
        ], className="g-3 mt-1")),
    ])), className="mt-3"),

    html.P("Built with Dash + Plotly on PostgreSQL · data from TMDB. This product uses the "
           "TMDB API but is not endorsed or certified by TMDB.",
           className="text-center mt-3 mb-1", style={"fontSize": "0.74rem", "color": "#9AA1AC"}),
])


# ===========================================================================
# Callbacks
# ===========================================================================
@app.callback(
    Output("kpi-films", "children"), Output("kpi-rating", "children"),
    Output("kpi-mult", "children"), Output("kpi-roi", "children"),
    Output("kpi-profit", "children"), Output("kpi-hits", "children"),
    Output("g-scatter", "figure"), Output("g-band", "figure"),
    Output("g-genre-scatter", "figure"), Output("g-genre-bar", "figure"),
    Output("g-tier", "figure"), Output("g-perf", "figure"), Output("g-trend", "figure"),
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
        return ("0", "—", "—", "—", "$0", "—", e, e, e, e, e, e, e, e, e, e, e, [])

    profit_txt = money(df["profit"].sum())
    hits = (df["performance"] == "Hit (>=2x)").mean() * 100
    g = genre_rollup(df, genres)
    table = (df.sort_values("profit", ascending=False)
               [["film_id", "title", "release_year", "genres", "budget", "revenue",
                 "profit", "revenue_multiple", "roi_pct", "vote_average"]].to_dict("records"))

    return (
        f"{len(df):,}", f"{df['vote_average'].mean():.2f}",
        f"{df['revenue_multiple'].median():.1f}×", f"{df['roi_pct'].median():.0f}%",
        profit_txt, f"{hits:.0f}%",
        fig_scatter(df), fig_rating_band(df), fig_genre_scatter(g), fig_genre_bar(g),
        fig_tier_bars(df), fig_perf_donut(df), fig_trend(df),
        fig_leaderboard(df, "revenue", "Biggest box office", color=PALETTE[0]),
        fig_leaderboard(df, "profit", "Biggest profit", color="#2E8B8B"),
        fig_leaderboard(df, "revenue_multiple", "Best return on budget (budget ≥ $10M)",
                        money_fmt=False, suffix="×", color=PALETTE[2], min_budget=10_000_000),
        fig_leaderboard(df, "profit", "Biggest losses", largest=False, color="#B5524B"),
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
    Output("film-detail", "children"), Output("film-picker", "value"),
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
    if fid is None:
        return DETAIL_PROMPT, no_update
    try:
        fid = int(fid)
    except (TypeError, ValueError):
        return DETAIL_PROMPT, no_update
    row = FILMS[FILMS["film_id"] == fid]
    if row.empty:
        return DETAIL_PROMPT, no_update
    # Don't echo a value back to the picker when the picker (or initial load) is the source.
    new_value = no_update if trig in (None, "film-picker") else fid
    return film_detail(row.iloc[0]), new_value


@app.callback(Output("f-year", "value"), Input("refresh", "n_clicks"),
              State("f-year", "value"), prevent_initial_call=True)
def refresh_data(_n, year_range):
    """Re-pull films from PostgreSQL without a restart (live/refreshed data)."""
    global FILMS
    FILMS = load_films()
    return year_range


if __name__ == "__main__":
    app.run(debug=True, port=8050)
