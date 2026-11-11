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
items = [i["name"] for i in cfg["items"]]
targets = {i["name"]: i.get("max_price") for i in cfg["items"]}
found = search_many(items, cfg.get("global_keywords", []))

for item, (rows, errs) in found.items():
    if not rows:
        send(f"🔎 <b>{item}</b>\nNo results today." + (f"\n⚠️ {'; '.join(errs)}" if errs else ""))
        continue
    best = rows[0]
    hit = targets.get(item) and best["price"] <= targets[item]
    head = ("🔥 UNDER YOUR TARGET — " if hit else "🏆 Best price — ") + f"<b>{item}</b>\n"
    send(head + line(best), best["image"])
    if len(rows) > 1:
        send("Other options:\n\n" + "\n\n".join(line(r) for r in rows[1:3]))
