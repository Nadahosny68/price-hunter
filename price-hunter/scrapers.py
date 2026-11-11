"""Price Hunter - search engines for Amazon.eg, Noon, Jumia + Google Shopping (brand sites)."""
import json, os, re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}
TIMEOUT = 20


def _num(text):
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(text or ""))
    return float(m.group().replace(",", "")) if m else None


def _row(store, title, price, link, image="", currency="EGP"):
    return {"store": store, "title": (title or "").strip(), "price": price,
            "currency": currency, "link": link, "image": image or "", "tag": ""}


def jumia(q):
    r = requests.get(f"https://www.jumia.com.eg/catalog/?q={quote_plus(q)}",
                     headers=HEADERS, timeout=TIMEOUT)
    soup, out = BeautifulSoup(r.text, "html.parser"), []
    for a in soup.select("article.prd"):
        link = a.select_one("a.core")
        name, prc, img = a.select_one(".name"), a.select_one(".prc"), a.select_one("img")
        if not (link and name and prc):
            continue
        out.append(_row("Jumia", name.text, _num(prc.text),
                        "https://www.jumia.com.eg" + link.get("href", ""),
                        img.get("data-src") or img.get("src") if img else ""))
    return out


def amazon(q):
    r = requests.get(f"https://www.amazon.eg/s?k={quote_plus(q)}", headers=HEADERS, timeout=TIMEOUT)
    if "captcha" in r.text.lower():
        raise RuntimeError("Amazon blocked the request (captcha)")
    soup, out = BeautifulSoup(r.text, "html.parser"), []
    for c in soup.select('div[data-component-type="s-search-result"]'):
        t, p = c.select_one("h2"), c.select_one("span.a-price span.a-offscreen")
        a, img = c.select_one("h2 a") or c.select_one("a.a-link-normal"), c.select_one("img.s-image")
        if not (t and p and a):
            continue
        out.append(_row("Amazon.eg", t.text, _num(p.text),
                        "https://www.amazon.eg" + a.get("href", "").split("?")[0],
                        img.get("src") if img else ""))
    return out


def _walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def noon(q):
    r = requests.get(f"https://www.noon.com/egypt-en/search/?q={quote_plus(q)}",
                     headers=HEADERS, timeout=TIMEOUT)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
    if not m:
        raise RuntimeError("Noon blocked the request or changed its page")
    out, seen = [], set()
    for d in _walk(json.loads(m.group(1))):
        if d.get("name") and d.get("sku") and d.get("url") and (d.get("sale_price") or d.get("price")):
            if d["sku"] in seen:
                continue
            seen.add(d["sku"])
            img = f"https://f.nooncdn.com/p/{d['image_key']}.jpg" if d.get("image_key") else ""
            out.append(_row("Noon", d["name"], _num(d.get("sale_price") or d.get("price")),
                            f"https://www.noon.com/egypt-en/{d['url']}/{d['sku']}/p/", img))
    return out


def google_shopping(q):
    """Covers brand websites and other Egyptian shops. Needs a SERPAPI_KEY (free tier: 100/month)."""
    key = os.getenv("SERPAPI_KEY")
    if not key:
        return []
    r = requests.get("https://serpapi.com/search.json", timeout=TIMEOUT, params={
        "engine": "google_shopping", "q": q, "gl": "eg", "hl": "en",
        "google_domain": "google.com.eg", "api_key": key})
    out = []
    for s in r.json().get("shopping_results", []):
        link = s.get("product_link") or s.get("link")
        if link and s.get("extracted_price"):
            out.append(_row(s.get("source", "Web"), s.get("title"), float(s["extracted_price"]),
                            link, s.get("thumbnail"), "EGP"))
    return out


SOURCES = {"Jumia": jumia, "Amazon.eg": amazon, "Noon": noon, "Google Shopping (brand sites)": google_shopping}


def _relevant(item, title, need=0.6):
    words = [w for w in re.findall(r"\w+", item.lower()) if len(w) > 1]
    t = title.lower()
    return not words or sum(w in t for w in words) / len(words) >= need


def search_item(item, keywords=(), sources=None, top=5):
    """Search one item (plus optional deal keywords). Returns (results, errors)."""
    sources = sources or list(SOURCES)
    queries = [(item, "")] + [(f"{item} {k}", k) for k in keywords if k.strip()]
    jobs = [(s, q, tag) for s in sources for q, tag in queries]
    results, errors = {}, []

    def run(job):
        s, q, tag = job
        try:
            return [(dict(r, tag=tag)) for r in SOURCES[s](q)]
        except Exception as e:
            errors.append(f"{s}: {e}")
            return []

    with ThreadPoolExecutor(8) as ex:
        for rows in ex.map(run, jobs):
            for r in rows:
                if r["price"] and _relevant(item, r["title"]):
                    old = results.get(r["link"])
                    if not old or (r["tag"] and not old["tag"]):
                        results[r["link"]] = r
    ranked = sorted(results.values(), key=lambda r: r["price"])
    return ranked[:top], sorted(set(errors))


def search_many(items, keywords=(), sources=None, top=5):
    with ThreadPoolExecutor(4) as ex:
        outs = list(ex.map(lambda i: search_item(i, keywords, sources, top), items))
    return {i: o for i, o in zip(items, outs)}
