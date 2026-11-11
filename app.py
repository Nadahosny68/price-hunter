import base64, json, os, time
import pandas as pd
import requests, streamlit as st
from scrapers import SOURCES, DEFAULT_SOURCES, search_many

for _k in ("SERPER_API_KEY", "SERPAPI_KEY"):
    if _k in st.secrets:
        os.environ[_k] = st.secrets[_k]

st.set_page_config(page_title="Price Hunter", page_icon="🛒", layout="centered")
st.title("🛒 Price Hunter")
tab1, tab2 = st.tabs(["Search now", "Daily watchlist"])


@st.cache_data(ttl=1800, show_spinner=False)
def cached_search(specs_json, keywords, sources, wide, nonce):
    return search_many(json.loads(specs_json), list(keywords), list(sources), wide=wide)


def card(r, crown=False):
    with st.container(border=True):
        c1, c2 = st.columns([1, 2])
        if r["image"]:
            c1.image(r["image"])
        tag = f" · 🏷️ {r['tag']}" if r["tag"] else ""
        price = f"**{'🏆 ' if crown else ''}{r['price']:,.0f} {r['currency']}**" if r["price"] else "**check price**"
        c2.markdown(f"{price} · {r['store']}{tag}")
        c2.write(r["title"][:110])
        if r.get("note"):
            c2.caption(r["note"])
        c2.link_button("Open", r["link"])


with tab1:
    items_txt = st.text_area("Items (one per line)", placeholder="mlay t14 pro\nPhilips air fryer", height=110)
    kws = st.text_input("Deal keywords (comma separated)", placeholder="black friday, 11.11")
    excl = st.text_input("Exclude words (optional)", placeholder="refurbished, used")
    min_p = st.number_input("Ignore results cheaper than (EGP)", min_value=0, value=0, step=100)
    wide = st.checkbox("Wide search (tries spelling variants like malay / mlay)", value=True)
    fresh = st.checkbox("Fresh search (skip the 30-minute cache)", value=False)
    srcs = st.multiselect("Sources", list(SOURCES), default=DEFAULT_SOURCES)
    if st.button("Find best prices", type="primary", use_container_width=True):
        names = [i.strip() for i in items_txt.splitlines() if i.strip()]
        keywords = tuple(k.strip() for k in kws.split(",") if k.strip())
        specs = [{"name": n, "min_price": min_p, "exclude": [e.strip() for e in excl.split(",") if e.strip()]}
                 for n in names]
        if not names:
            st.warning("Enter at least one item.")
        else:
            with st.spinner("Searching..."):
                found = cached_search(json.dumps(specs), keywords, tuple(srcs), wide, time.time() if fresh else 0)
            for name, res in found.items():
                st.subheader(name)
                if res["best"]:
                    st.markdown("**Best matches**")
                    for i, r in enumerate(res["best"]):
                        card(r, crown=(i == 0))
                if res["related"]:
                    st.markdown("**Related items**")
                    for r in res["related"]:
                        card(r)
                if res["links"]:
                    with st.expander(f"Pages to check on Noon / Amazon / Jumia ({len(res['links'])})"):
                        for r in res["links"]:
                            card(r)
                if res["other"]:
                    with st.expander(f"Very cheap or accessories ({len(res['other'])})"):
                        for r in res["other"]:
                            card(r)
                if not (res["best"] or res["related"] or res["links"]):
                    st.info("Nothing matched. Open 'Search details' below to see why.")
                with st.expander("Search details"):
                    for s, v in res["stats"].items():
                        st.write(f"**{s}**: {v['found']} found → {v['kept']} matched")
                    for e in res["errors"]:
                        st.caption(f"⚠️ {e}")

with tab2:
    st.write("These items are searched every day by GitHub Actions and sent to your Telegram.")
    if "GH_TOKEN" not in st.secrets:
        st.info("Add GH_TOKEN and GH_REPO to the app secrets to edit the watchlist here.")
        st.stop()
    repo, token = st.secrets["GH_REPO"], st.secrets["GH_TOKEN"]
    url = f"https://api.github.com/repos/{repo}/contents/watchlist.json"
    H = {"Authorization": f"Bearer {token}"}
    cur = requests.get(url, headers=H)
    if not cur.ok:
        st.error(f"GitHub error {cur.status_code}. Check GH_TOKEN and GH_REPO.")
        st.stop()
    cur = cur.json()
    data = json.loads(base64.b64decode(cur["content"]))
    df = pd.DataFrame([{"name": i.get("name", ""), "min_price": i.get("min_price"),
                        "max_price": i.get("max_price"), "exclude": ", ".join(i.get("exclude", []))}
                       for i in data.get("items", [])], columns=["name", "min_price", "max_price", "exclude"])
    df["min_price"] = pd.to_numeric(df["min_price"])
    df["max_price"] = pd.to_numeric(df["max_price"])
    st.caption("max_price = alert me at or below this price. min_price = ignore anything cheaper. "
               "Tap the + row to add an item.")
    edited = st.data_editor(df, num_rows="dynamic", use_container_width=True, key="wl")
    gk = st.text_input("Deal keywords", ", ".join(data.get("global_keywords", [])))
    if st.button("Save watchlist", use_container_width=True):
        clean = lambda v: None if pd.isna(v) else float(v)
        items = [{"name": str(r["name"]).strip(), "min_price": clean(r["min_price"]), "max_price": clean(r["max_price"]),
                  "exclude": [e.strip() for e in str(r["exclude"] or "").split(",") if e.strip() and e != "nan"]}
                 for _, r in edited.iterrows() if str(r["name"]).strip() not in ("", "nan", "None")]
        new = {"global_keywords": [k.strip() for k in gk.split(",") if k.strip()], "items": items}
        body = {"message": "update watchlist", "sha": cur["sha"],
                "content": base64.b64encode(json.dumps(new, indent=2, ensure_ascii=False).encode()).decode()}
        res = requests.put(url, headers=H, json=body)
        st.success("Saved ✅") if res.ok else st.error(f"Could not save: {res.status_code}")
