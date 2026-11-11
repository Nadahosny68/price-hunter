import base64, json, os
import pandas as pd
import requests, streamlit as st
from scrapers import SOURCES, DEFAULT_SOURCES, search_many

if "SERPAPI_KEY" in st.secrets:
    os.environ["SERPAPI_KEY"] = st.secrets["SERPAPI_KEY"]

st.set_page_config(page_title="Price Hunter", page_icon="🛒", layout="centered")
st.title("🛒 Price Hunter")
tab1, tab2 = st.tabs(["Search now", "Daily watchlist"])

with tab1:
    items_txt = st.text_area("Items (one per line)", placeholder="iPhone 15\nPhilips air fryer", height=110)
    kws = st.text_input("Deal keywords (comma separated)", placeholder="black friday, 11.11")
    excl = st.text_input("Exclude words (optional)", placeholder="pro max, plus, refurbished")
    min_p = st.number_input("Ignore results cheaper than (EGP)", min_value=0, value=0, step=100)
    srcs = st.multiselect("Sources", list(SOURCES), default=DEFAULT_SOURCES)
    if st.button("Find best prices", type="primary", use_container_width=True):
        names = [i.strip() for i in items_txt.splitlines() if i.strip()]
        keywords = [k.strip() for k in kws.split(",") if k.strip()]
        specs = [{"name": n, "min_price": min_p, "exclude": [e.strip() for e in excl.split(",")]} for n in names]
        if not names:
            st.warning("Enter at least one item.")
        else:
            with st.spinner("Searching..."):
                found = search_many(specs, keywords, srcs)
            for name, res in found.items():
                st.subheader(name)
                if not res["rows"]:
                    st.info("No matching results. Try fewer words, or check the details below.")
                for i, r in enumerate(res["rows"]):
                    with st.container(border=True):
                        c1, c2 = st.columns([1, 2])
                        if r["image"]:
                            c1.image(r["image"])
                        tag = f" · 🏷️ {r['tag']}" if r["tag"] else ""
                        c2.markdown(f"**{'🏆 ' if i == 0 else ''}{r['price']:,.0f} {r['currency']}** · {r['store']}{tag}")
                        c2.write(r["title"][:110])
                        c2.link_button("Open", r["link"])
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
                        "max_price": i.get("max_price"),
                        "exclude": ", ".join(i.get("exclude", []))} for i in data.get("items", [])],
                      columns=["name", "min_price", "max_price", "exclude"])
    df["min_price"] = pd.to_numeric(df["min_price"])
    df["max_price"] = pd.to_numeric(df["max_price"])
    st.caption("max_price = alert me when the price is at or below this. "
               "min_price = ignore anything cheaper (accessories). Tap the + row to add an item.")
    edited = st.data_editor(df, num_rows="dynamic", use_container_width=True, key="wl")
    gk = st.text_input("Deal keywords", ", ".join(data.get("global_keywords", [])))

    if st.button("Save watchlist", use_container_width=True):
        def clean(v):
            return None if pd.isna(v) else float(v)
        items = [{"name": str(r["name"]).strip(), "min_price": clean(r["min_price"]),
                  "max_price": clean(r["max_price"]),
                  "exclude": [e.strip() for e in str(r["exclude"] or "").split(",") if e.strip() and e != "nan"]}
                 for _, r in edited.iterrows() if str(r["name"]).strip() not in ("", "nan", "None")]
        new = {"global_keywords": [k.strip() for k in gk.split(",") if k.strip()], "items": items}
        body = {"message": "update watchlist", "sha": cur["sha"],
                "content": base64.b64encode(json.dumps(new, indent=2, ensure_ascii=False).encode()).decode()}
        res = requests.put(url, headers=H, json=body)
        st.success("Saved ✅") if res.ok else st.error(f"Could not save: {res.status_code}")
