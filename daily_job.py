"""Runs daily on GitHub Actions: searches the watchlist and sends results to Telegram."""
import json, os
import requests
from scrapers import search_many

TOKEN, CHAT = os.environ["TELEGRAM_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]
API = f"https://api.telegram.org/bot{TOKEN}"


def send(text, photo=None):
    if photo:
        r = requests.post(f"{API}/sendPhoto", data={"chat_id": CHAT, "photo": photo,
                          "caption": text[:1000], "parse_mode": "HTML"})
        if r.ok:
            return
    requests.post(f"{API}/sendMessage", data={"chat_id": CHAT, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": True})


def line(r):
    tag = f" 🏷️{r['tag']}" if r["tag"] else ""
    return f"<b>{r['price']:,.0f} {r['currency']}</b> · {r['store']}{tag}\n{r['title'][:90]}\n{r['link']}"


cfg = json.load(open("watchlist.json", encoding="utf-8"))
specs = []
for i in cfg["items"]:
    ex = i.get("exclude", [])
    ex = [e.strip() for e in ex.split(",")] if isinstance(ex, str) else ex
    specs.append({"name": i["name"], "min_price": i.get("min_price"),
                  "max_price": i.get("max_price"), "exclude": ex})

found = search_many(specs, cfg.get("global_keywords", []))
for spec in specs:
    res = found[spec["name"]]
    item = spec["name"]
    rows = res["best"] or res["related"]
    if not rows:
        msg = f"🔎 <b>{item}</b>\nNo priced results today."
        if res["links"]:
            msg += "\nPages to check:\n" + "\n".join(r["link"] for r in res["links"][:3])
        if res["errors"]:
            msg += "\n⚠️ " + "; ".join(res["errors"])[:300]
        send(msg)
        continue
    best = rows[0]
    hit = spec["max_price"] and best["price"] <= spec["max_price"]
    head = ("🔥 UNDER YOUR TARGET — " if hit else "🏆 Best price — ") + f"<b>{item}</b>\n"
    send(head + line(best), best["image"])
    if len(rows) > 1:
        send("Other options:\n\n" + "\n\n".join(line(r) for r in rows[1:3]))
