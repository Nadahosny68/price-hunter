import base64, json, os
import requests, streamlit as st
from scrapers import SOURCES, search_many

for k in ("SERPAPI_KEY",):
    if k in st.secrets:
        os.environ[k] = st.secrets[k]

st.set_page_config(page_title="Price Hunter", page_icon="🛒", layout="centered")
st.title("🛒 Price Hunter")

tab1, tab2 = st.tabs(["Search now", "Daily watchlist"])

with tab1:
    items_txt = st.text_area("Items (one per line)", placeholder="iPhone 15\nPhilips air fryer", height=110)
    kws = st.text_input("Deal keywords (comma separated)", placeholder="black friday, 11.11")
    srcs = st.multiselect("Sources", list(SOURCES), default=list(SOURCES))
    if st.button("Find best prices", type="primary", use_container_width=True):
        items = [i.strip() for i in items_txt.splitlines() if i.strip()]
        keywords = [k.strip() for k in kws.split(",") if k.strip()]
        if not items:
            st.warning("Enter at least one item.")
        else:
            with st.spinner("Searching..."):
                found = search_many(items, keywords, srcs)
            for item, (rows, errs) in found.items():
                st.subheader(item)
                for e in errs:
                    st.caption(f"⚠️ {e}")
                if not rows:
                    st.info("No results.")
                for i, r in enumerate(rows):
                    with st.container(border=True):
                        c1, c2 = st.columns([1, 2])
                        if r["image"]:
                            c1.image(r["image"])
                        badge = "🏆 " if i == 0 else ""
                        tag = f" · 🏷️ {r['tag']}" if r["tag"] else ""
                        c2.markdown(f"**{badge}{r['price']:,.0f} {r['currency']}** · {r['store']}{tag}")
                        c2.write(r["title"][:110])
                        c2.link_button("Open", r["link"])

with tab2:
    st.write("Items here are searched every day by GitHub Actions and sent to your Telegram.")
    if "GH_TOKEN" not in st.secrets:
        st.info("Add GH_TOKEN and GH_REPO to the app's secrets to edit the watchlist from here, "
                "or edit watchlist.json directly on GitHub.")
    else:
        repo, token = st.secrets["GH_REPO"], st.secrets["GH_TOKEN"]
        url = f"https://api.github.com/repos/{repo}/contents/watchlist.json"
        H = {"Authorization": f"Bearer {token}"}
        cur = requests.get(url, headers=H)
if not cur.ok:
    st.error(f"GitHub error {cur.status_code}. Check GH_TOKEN and GH_REPO.")
    st.stop()
cur = cur.json()
        data = json.loads(base64.b64decode(cur["content"]))
        txt = st.text_area("Watchlist (JSON)", json.dumps(data, indent=2, ensure_ascii=False), height=300)
        if st.button("Save watchlist", use_container_width=True):
            try:
                new = json.loads(txt)
                body = {"message": "update watchlist", "sha": cur["sha"],
                        "content": base64.b64encode(json.dumps(new, indent=2, ensure_ascii=False).encode()).decode()}
                requests.put(url, headers=H, json=body).raise_for_status()
                st.success("Saved ✅")
            except Exception as e:
                st.error(f"Could not save: {e}")
