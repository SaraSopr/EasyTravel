"""
Streamlit dashboard for thesis evaluation metrics.
Run: streamlit run pipeline/dashboard.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.metrics import (
    PREFERENCE_KEYS,
    get_all_itineraries_metrics,
    get_classification_metrics,
    get_summary_stats,
    get_tourism_metrics,
)

# ── page config ────────────────────────────────────────────────────

st.set_page_config(
    page_title="POI Recommender — Thesis Evaluation",
    page_icon="🗺️",
    layout="wide",
)

# ── cached loaders ─────────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def load_summary(city: str | None) -> dict:
    return asyncio.run(get_summary_stats(city=city))


@st.cache_data(ttl=60, show_spinner=False)
def load_itineraries(city: str | None) -> list[dict]:
    return asyncio.run(get_all_itineraries_metrics(city=city))


@st.cache_data(ttl=60, show_spinner=False)
def load_classification_metrics(city: str | None) -> dict:
    return asyncio.run(get_classification_metrics(city=city))


@st.cache_data(ttl=60, show_spinner=False)
def load_tourism_metrics(city: str | None) -> dict:
    return asyncio.run(get_tourism_metrics(city=city))


# ── sidebar ────────────────────────────────────────────────────────

st.sidebar.title("Filters")
city_input = st.sidebar.text_input("City (leave empty for all)", value="")
city = city_input.strip() or None

# ── load data ──────────────────────────────────────────────────────

with st.spinner("Loading metrics…"):
    summary     = load_summary(city)
    itineraries = load_itineraries(city)

if "error" in summary:
    st.error(f"No data found: {summary['error']}")
    st.stop()

# ── title ──────────────────────────────────────────────────────────

st.title("🗺️ POI Recommender — Thesis Evaluation Dashboard")
st.caption(
    f"City: **{city or 'All'}**  ·  "
    f"Itineraries: **{summary['total_itineraries']}**"
)

# ── summary cards ──────────────────────────────────────────────────

st.subheader("Summary")
c1, c2, c3, c4 = st.columns(4)

c1.metric(
    "Mean Preference Score",
    f"{summary['mean_preference_score']:.2f}" if summary["mean_preference_score"] else "—",
    help="Cosine similarity between user preferences and POI vectors. Higher = more personalized.",
)
c2.metric(
    "Std Preference Score",
    f"{summary['std_preference_score']:.2f}" if summary["std_preference_score"] else "—",
    help="Lower = more consistent personalization across itineraries.",
)
c3.metric(
    "Mean Shannon Entropy",
    f"{summary['mean_shannon_entropy']:.2f}",
    help="Category diversity per itinerary. Higher = more varied (max ~2.8 for 7 categories).",
)
c4.metric(
    "Mean Distance/Day",
    f"{summary['mean_distance_per_day_km']:.1f} km" if summary["mean_distance_per_day_km"] else "—",
    help="Average km walked per day. Lower = more geographically coherent.",
)

st.divider()

# ── preference score distribution ─────────────────────────────────

st.subheader("Preference Score Distribution")
st.caption(
    "How well each itinerary matches the user's declared preferences. "
    "This is the main personalization metric."
)

scores = [m["mean_preference_score"] for m in itineraries if m["mean_preference_score"] is not None]
if scores:
    fig_hist = px.histogram(
        x=scores, nbins=20,
        labels={"x": "Mean Preference Score", "y": "Count"},
        color_discrete_sequence=["#6366f1"],
    )
    fig_hist.update_layout(showlegend=False, height=300, margin=dict(t=20, b=20))
    st.plotly_chart(fig_hist, width='stretch')

st.divider()

# ── category distribution ──────────────────────────────────────────

st.subheader("Category Distribution")
col_l, col_r = st.columns(2)

with col_l:
    st.caption("Across all itineraries")
    cat_dist = summary["category_distribution"]
    if cat_dist:
        fig_cat = px.pie(
            values=list(cat_dist.values()),
            names=list(cat_dist.keys()),
            color_discrete_sequence=px.colors.qualitative.Pastel,
        )
        fig_cat.update_layout(height=300, margin=dict(t=20, b=20))
        st.plotly_chart(fig_cat, width='stretch')

with col_r:
    st.caption("Per-itinerary entropy (diversity)")
    entropies = [m["shannon_entropy"] for m in itineraries]
    fig_ent = px.box(
        y=entropies,
        labels={"y": "Shannon Entropy"},
        color_discrete_sequence=["#a78bfa"],
    )
    fig_ent.update_layout(height=300, margin=dict(t=20, b=20))
    st.plotly_chart(fig_ent, width='stretch')

st.divider()

# ── per-stop preference scores ─────────────────────────────────────

st.subheader("Per-Stop Preference Scores")
st.caption(
    "Preference score for each activity stop across all itineraries. "
    "Food stops are excluded (mandatory, not personalized)."
)

all_stops = [
    {"name": s["name"], "category": s["category"], "score": s["preference_score"], "city": m["city"]}
    for m in itineraries
    for s in m["per_stop_scores"]
    if s["preference_score"] is not None
]

if all_stops:
    df_stops = pd.DataFrame(all_stops)
    fig_stops = px.box(
        df_stops, x="category", y="score", color="category",
        labels={"score": "Preference Score", "category": "Category"},
        color_discrete_sequence=px.colors.qualitative.Pastel,
    )
    fig_stops.update_layout(showlegend=False, height=350, margin=dict(t=20, b=20))
    st.plotly_chart(fig_stops, width='stretch')

st.divider()

# ── distance analysis ──────────────────────────────────────────────

st.subheader("Geographic Coherence")
st.caption("Distance walked per day. Lower = more geographically coherent itineraries.")

dist_data = [
    {"city": m["city"], "km_per_day": m["mean_distance_per_day_km"], "total_km": m["total_distance_km"]}
    for m in itineraries if m["mean_distance_per_day_km"] is not None
]

if dist_data:
    df_dist = pd.DataFrame(dist_data)
    fig_dist = px.box(
        df_dist, x="city", y="km_per_day", color="city",
        labels={"km_per_day": "Km/day", "city": "City"},
        color_discrete_sequence=px.colors.qualitative.Pastel,
    )
    fig_dist.update_layout(showlegend=False, height=300, margin=dict(t=20, b=20))
    st.plotly_chart(fig_dist, width='stretch')

st.divider()

# ── itinerary detail ───────────────────────────────────────────────

st.subheader("Itinerary Detail")
st.caption("Select an itinerary to inspect per-stop scores and vectors.")

itin_options = {
    f"{m['city']} — {m['itinerary_id'][:8]}…  (score: {m['mean_preference_score']:.2f})": m
    for m in itineraries
    if m["mean_preference_score"] is not None
}

if itin_options:
    selected_label = st.selectbox("Itinerary", options=list(itin_options.keys()))
    selected = itin_options[selected_label]

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("**User preferences (radar)**")
        prefs = selected["user_preferences"]
        if prefs:
            keys = list(prefs.keys())
            vals = list(prefs.values())
            fig_radar = go.Figure(go.Scatterpolar(
                r=vals + [vals[0]],
                theta=keys + [keys[0]],
                fill="toself",
                fillcolor="rgba(99,102,241,0.2)",
                line=dict(color="#6366f1", width=2),
            ))
            fig_radar.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
                showlegend=False, height=320, margin=dict(t=30, b=20),
            )
            st.plotly_chart(fig_radar, width='stretch')

    with col_b:
        st.markdown("**Per-stop preference scores (bar)**")
        stops_scored = [
            {"Stop": s["name"][:28], "Day": s["day"], "Category": s["category"], "Score": s["preference_score"]}
            for s in selected["per_stop_scores"]
            if s["preference_score"] is not None
        ]
        if stops_scored:
            df_bar = pd.DataFrame(stops_scored).sort_values(["Day", "Stop"])
            fig_bar = px.bar(
                df_bar, x="Stop", y="Score", color="Category",
                range_y=[0, 1],
                color_discrete_sequence=px.colors.qualitative.Pastel,
            )
            fig_bar.update_layout(
                height=320, margin=dict(t=30, b=20),
                xaxis_tickangle=-40, showlegend=True,
            )
            st.plotly_chart(fig_bar, width='stretch')

    with st.expander("Raw stop data"):
        rows = []
        for s in selected["per_stop_scores"]:
            row = {
                "day":              s["day"],
                "position":         s["position"],
                "name":             s["name"],
                "category":         s["category"],
                "preference_score": s["preference_score"],
                "rating":           s["rating"],
            }
            for key, val in zip(PREFERENCE_KEYS, s["feature_vector"]):
                row[key] = round(val, 3)
            rows.append(row)
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

st.divider()

# ── LLM classification quality ─────────────────────────────────────

st.subheader("LLM Classification Quality")
clf = load_classification_metrics(city)

if "error" in clf:
    st.info(f"No classification data yet: {clf['error']}")
else:
    total_clf = clf["total_classified"]
    ca1, ca2, ca3, ca4 = st.columns(4)
    ca1.metric(
        "Agreement Rate",
        f"{clf['category_agreement_rate']:.1%}",
        help="% of POIs where LLM1 and LLM2 agreed on category.",
    )
    ca2.metric(
        "Mean Cosine Distance",
        f"{clf['mean_cosine_distance']:.3f}" if clf["mean_cosine_distance"] is not None else "—",
        help="Distance between LLM1 and LLM2 feature vectors. Lower = more consistent.",
    )
    ca3.metric(
        "Arbitration Rate",
        f"{clf['arbitration_rate']:.1%}",
        help="% of POIs that required LLM3 arbitration (medium + failed).",
    )
    ca4.metric(
        "Failed Rate",
        f"{clf['failed_rate']:.1%}",
        help="% of POIs where all classifiers failed to produce a valid output.",
    )

    col_conf, col_dis = st.columns(2)

    with col_conf:
        st.caption("Confidence distribution")
        conf_dist = clf["confidence_distribution"]
        if conf_dist:
            fig_conf = px.pie(
                values=list(conf_dist.values()),
                names=list(conf_dist.keys()),
                color_discrete_map={"high": "#86efac", "medium": "#fcd34d", "failed": "#fca5a5"},
            )
            fig_conf.update_layout(height=280, margin=dict(t=20, b=20))
            st.plotly_chart(fig_conf, width="stretch")

    with col_dis:
        st.caption("Top disagreement pairs (LLM1 vs LLM2)")
        top_dis = clf["top_disagreements"]
        if top_dis:
            fig_dis = px.bar(
                x=list(top_dis.values()),
                y=list(top_dis.keys()),
                orientation="h",
                labels={"x": "Count", "y": "Category pair"},
                color_discrete_sequence=["#818cf8"],
            )
            fig_dis.update_layout(height=280, margin=dict(t=20, b=20), showlegend=False)
            st.plotly_chart(fig_dis, width="stretch")

    st.caption("Per-category vector consistency (where categories agreed — lower = more consistent)")
    vc = clf["vector_consistency"]
    if vc:
        vc_df = pd.DataFrame([
            {"category": cat, "mean_cosine_distance": v["mean_cosine_distance"], "count": v["count"]}
            for cat, v in vc.items()
        ]).sort_values("mean_cosine_distance")
        fig_vc = px.bar(
            vc_df, x="category", y="mean_cosine_distance",
            labels={"mean_cosine_distance": "Mean cosine distance", "category": "Category"},
            color="mean_cosine_distance",
            color_continuous_scale="RdYlGn_r",
            hover_data=["count"],
        )
        fig_vc.update_layout(height=300, margin=dict(t=20, b=20), showlegend=False,
                             coloraxis_showscale=False)
        st.plotly_chart(fig_vc, width="stretch")

st.divider()

# ── tourism validation quality ─────────────────────────────────────

st.subheader("Tourism Validation Quality")
tv = load_tourism_metrics(city)

if "error" in tv:
    st.info(f"No tourism validation data yet: {tv['error']}")
else:
    tb1, tb2, tb3 = st.columns(3)
    tb1.metric(
        "Touristic Rate",
        f"{tv['touristic_rate']:.1%}",
        help="% of validated POIs accepted as touristic.",
    )
    tb2.metric(
        "LLM2 Needed",
        f"{tv['llm2_needed_rate']:.1%}",
        help="% of POIs where LLM1 was uncertain and LLM2 was called.",
    )
    tb3.metric(
        "Disagreement Rate",
        f"{tv['disagreement_rate']:.1%}",
        help="Of uncertain cases: % where LLM1 and LLM2 disagreed.",
    )

    col_vt, col_dur = st.columns(2)

    with col_vt:
        st.caption("Visit type distribution (touristic POIs)")
        vt_dist = tv["visit_type_distribution"]
        if any(vt_dist.values()):
            fig_vt = px.pie(
                values=list(vt_dist.values()),
                names=list(vt_dist.keys()),
                color_discrete_sequence=px.colors.qualitative.Pastel,
            )
            fig_vt.update_layout(height=280, margin=dict(t=20, b=20))
            st.plotly_chart(fig_vt, width="stretch")

    with col_dur:
        st.caption("Mean visit duration (minutes)")
        dur = tv["duration_stats"]
        indoor_m = dur["indoor_mean_minutes"]
        outdoor_m = dur["outdoor_mean_minutes"]
        if indoor_m or outdoor_m:
            fig_dur = px.bar(
                x=["indoor", "outdoor"],
                y=[indoor_m or 0, outdoor_m or 0],
                labels={"x": "Visit type", "y": "Mean minutes"},
                color_discrete_sequence=["#a5b4fc", "#6ee7b7"],
            )
            fig_dur.update_layout(height=280, margin=dict(t=20, b=20), showlegend=False)
            st.plotly_chart(fig_dur, width="stretch")

st.divider()

# ── export ─────────────────────────────────────────────────────────

st.subheader("Export")
if itineraries:
    df_export = pd.DataFrame([
        {
            "itinerary_id":             m["itinerary_id"],
            "city":                     m["city"],
            "num_days":                 m["num_days"],
            "total_stops":              m["total_stops"],
            "activity_stops":           m["activity_stops"],
            "mean_preference_score":    m["mean_preference_score"],
            "shannon_entropy":          m["shannon_entropy"],
            "total_distance_km":        m["total_distance_km"],
            "mean_distance_per_day_km": m["mean_distance_per_day_km"],
        }
        for m in itineraries
    ])
    st.download_button(
        label="Download CSV",
        data=df_export.to_csv(index=False),
        file_name=f"metrics_{city or 'all'}.csv",
        mime="text/csv",
    )
