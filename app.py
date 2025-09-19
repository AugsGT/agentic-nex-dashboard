import os
import json
import pandas as pd
import streamlit as st
import altair as alt
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from datetime import datetime, time

# -----------------------
# Load secrets
# -----------------------
load_dotenv()
DATABASE_psy = os.getenv("DATABASE_psy")

engine = create_engine(DATABASE_psy)

# -----------------------
# Helpers
# -----------------------
def flatten_answers(raw):
    """Convert Meta answers JSON into flat dict"""
    if not raw:
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return {}
    flat = {}
    for item in raw:
        field = item.get("name") or item.get("key")
        value = item.get("values")
        if isinstance(value, list) and len(value) == 1:
            value = value[0]
        flat[field] = value
    return flat


@st.cache_data(ttl=300)
def load_leads(form_id=None, start_date=None, end_date=None):
    filters = ["1=1"]
    params = {}

    if form_id:
        filters.append("form_id = :form_id")
        params["form_id"] = form_id
    if start_date:
        filters.append("created_time >= :start_date")
        params["start_date"] = datetime.combine(start_date, time.min)
    if end_date:
        filters.append("created_time <= :end_date")
        params["end_date"] = datetime.combine(end_date, time.max)

    query = text(f"SELECT * FROM leads WHERE {' AND '.join(filters)}")

    df = pd.read_sql(query, engine, params=params)

    # Ensure datetime conversion
    if "created_time" in df.columns:
        df["created_time"] = pd.to_datetime(df["created_time"], errors="coerce")

    # Flatten answers and avoid duplicate columns
    if "answers" in df.columns:
        expanded = df["answers"].apply(flatten_answers).apply(pd.Series)
        # Add prefix to avoid duplicates
        expanded = expanded.add_prefix("answer_")
        df = pd.concat([df.drop(columns=["answers"]), expanded], axis=1)

    return df


# -----------------------
# Streamlit UI
# -----------------------
st.set_page_config(page_title="Meta Lead Ads Dashboard", layout="wide")
st.title("📊 Meta Lead Ads Dashboard")

with st.sidebar:
    st.header("Filters")
    form_id = st.text_input("Form ID (optional)")
    start_date = st.date_input("Start date")
    end_date = st.date_input("End date")

df = load_leads(form_id or None, start_date or None, end_date or None)

st.subheader("Raw Leads")
st.dataframe(df, use_container_width=True)

# CSV export
if not df.empty:
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="⬇️ Download Leads as CSV",
        data=csv,
        file_name="leads.csv",
        mime="text/csv",
    )

    # Leads over time chart
    if "created_time" in df.columns:
        chart = (
            alt.Chart(df)
            .mark_bar()
            .encode(
                x="yearmonthdate(created_time):O",
                y="count()",
                tooltip=["count()"]
            )
            .properties(title="Leads over Time", width=800)
        )
        st.altair_chart(chart, use_container_width=True)

    # Breakdown by form_id
    if "form_id" in df.columns:
        st.subheader("Leads by Form ID")
        form_chart = (
            alt.Chart(df)
            .mark_bar()
            .encode(
                x="form_id:O",
                y="count()",
                tooltip=["count()"]
            )
        )
        st.altair_chart(form_chart, use_container_width=True)

else:
    st.warning("No leads found for the given filters.")
