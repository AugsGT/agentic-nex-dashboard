import time
import json
import requests
import pandas as pd
import streamlit as st

# -----------------------
# Config
# -----------------------
st.set_page_config(page_title="Agentic Nex — Meta Lead Ads Dashboard", layout="wide")

GRAPH_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

# -----------------------
# Helpers
# -----------------------
@st.cache_data(ttl=300, show_spinner=False)
def graph_get(path, token, params=None):
    """GET wrapper with basic error handling and caching."""
    if not token:
        raise ValueError("Missing access token")
    url = f"{GRAPH_BASE}/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, params=params or {})
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"Non-JSON response from Graph API ({resp.status_code}): {resp.text[:300]}")
    if resp.status_code != 200:
        err = data.get("error", {})
        raise RuntimeError(f"Graph error {err.get('code')}: {err.get('message')}")
    return data

def get_page(token):
    """For Page Access Tokens, /me resolves to the Page itself."""
    page = graph_get("/me", token)
    return [{"id": page["id"], "name": page.get("name", page["id"])}]

def get_forms(page_id, token):
    data = graph_get(f"/{page_id}/leadgen_forms", token, params={"limit": 200})
    return [{"id": it["id"], "name": it.get("name", it["id"])} for it in data.get("data", [])]

def parse_lead(lead):
    row = {
        "lead_id": lead.get("id"),
        "created_time": lead.get("created_time"),
        "ad_id": lead.get("ad_id"),
        "adset_id": lead.get("adset_id"),
        "campaign_id": lead.get("campaign_id"),
        "platform": lead.get("platform"),
        "is_organic": lead.get("is_organic"),
    }
    fields = {f.get("name"): f.get("values", [None])[0] for f in lead.get("field_data", [])}
    row["full_name"] = fields.get("full_name") or fields.get("name")
    row["phone_number"] = fields.get("phone_number") or fields.get("phone")
    row["email"] = fields.get("email")
    row["city"] = fields.get("city")
    # Include all raw fields too
    for k, v in fields.items():
        row[f"field__{k}"] = v
    return row

def get_leads(form_id, token, limit=50, older_than=None, fields=None):
    """
    Robust lead fetcher that follows paging.next URLs.
    """
    collected = []
    if fields is None:
        fields = [
            "field_data",
            "created_time",
            "ad_id",
            "adset_id",
            "campaign_id",
            "is_organic",
            "platform",
            "id"
        ]

    base_url = f"{GRAPH_BASE}/{form_id}/leads"
    params = {"limit": min(max(1, int(limit)), 100), "fields": ",".join(fields)}
    if older_than:
        params["filtering"] = json.dumps([{"field": "time_created", "operator": "LESS_THAN", "value": int(older_than)}])

    headers = {"Authorization": f"Bearer {token}"}
    url = base_url
    first = True

    while len(collected) < limit and url:
        if first:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            first = False
        else:
            resp = requests.get(url, headers=headers, timeout=30)

        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError(f"Non-JSON response from Graph API ({resp.status_code}): {resp.text[:300]}")

        if resp.status_code != 200:
            err = data.get("error", {})
            raise RuntimeError(f"Graph error {err.get('code')}: {err.get('message')}")

        batch = data.get("data", [])
        if not batch:
            break

        collected.extend(batch)

        paging = data.get("paging", {})
        url = paging.get("next")

        if url:
            time.sleep(0.12)

    return collected[:limit]

# -----------------------
# Sidebar — Token Input
# -----------------------
st.sidebar.title("Meta Auth")
access_token = st.sidebar.text_input(
    "Page Access Token", 
    type="password", 
    help="Paste a valid *Page Access Token* with `leads_retrieval` permission."
)

if not access_token:
    st.warning("Enter a valid access token in the left sidebar to begin.")
    st.stop()

# -----------------------
# Main UI
# -----------------------
st.title("Agentic Nex — Facebook Lead Ads Dashboard")

with st.spinner("Loading page…"):
    pages = get_page(access_token)

if not pages:
    st.error("No page found. Double-check your Page Access Token.")
    st.stop()

page_map = {p["name"]: p["id"] for p in pages}
page_name = st.selectbox("Page", options=list(page_map.keys()))
page_id = page_map[page_name]

with st.spinner("Loading forms…"):
    forms = get_forms(page_id, access_token)

if not forms:
    st.warning("No lead forms found for this page.")
    st.stop()

form_map = {f["name"]: f["id"] for f in forms}
form_name = st.selectbox("Form", options=list(form_map.keys()))
form_id = form_map[form_name]

c1, c2 = st.columns([1,1])
with c1:
    limit = st.number_input("Limit", min_value=1, max_value=3200, value=20, step=10)
with c2:
    older_than = st.text_input("Older than (unix timestamp, optional)", value="")

run = st.button("Fetch Leads", type="primary")

# -----------------------
# Fetch & Display
# -----------------------
if run:
    ts = None
    if older_than.strip():
        try:
            ts = int(older_than)
        except Exception:
            st.error("Invalid 'Older than' timestamp. Use an integer unix epoch.")
            st.stop()

    with st.spinner("Fetching leads…"):
        leads = get_leads(form_id, access_token, limit=int(limit), older_than=ts)

    if not leads:
        st.info("No leads returned.")
        st.stop()

    flat = [parse_lead(ld) for ld in leads]
    df = pd.DataFrame(flat)

    st.subheader("Leads Table")
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.metric("Total leads fetched", len(df))

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("Download CSV", csv, file_name=f"leads_{form_id}.csv", mime="text/csv")

    with st.expander("Raw API Payload"):
        st.json(leads)
