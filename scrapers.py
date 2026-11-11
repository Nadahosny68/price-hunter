"""Price Hunter v2 - Jumia, Amazon.eg, Noon, Google Shopping (brand sites), with smart filtering."""
import json, os, re, statistics
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}

# Words that usually mean "accessory, not the product itself"
ACCESSORY_WORDS = {
    "case", "cases", "cover", "covers", "protector", "protectors", "tempered", "skin", "holder",
    "stand", "pouch", "sleeve", "film", "sticker", "stickers", "strap", "straps", "charger",
    "cable", "adapter", "جراب", "كفر", "غطاء", "حماية", "اسكرينة", "سكرينة", "شاحن", "كابل", "استيك",
}
BUNDLE_WORDS = {"with", "including", "free", "plus", "and", "+", "w/", "مع"}


def _num(text):
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(text or ""))
    return float(m.group().replace(",", "")) if m else None


def _row(store, title, price, link, image="", currency="EGP"):
    return {"store": store, "title": (title or "").strip(), "price": price,
            "currency": currency, "link": link, "image": image or "", "tag": "", "src": ""}


# ---------------------------------------------------------------- sources
def jumia(q):
    r = requests.get(f"https://www.jumia.com.eg/catalog/?q={quote_plus(q)}", headers=HEADERS, timeout=15)
    soup, out = BeautifulSoup(r.text, "html.parser"), []
    for a in soup.select("article.prd"):
        link, name, prc, img = a.select_one("a.core"), a.select_one(".name"), a.select_one(".prc"), a.select_one("img")
        if link and name and prc:
            out.append(_row("Jumia", name.text, _num(prc.text),
                            "https://www.jumia.com.eg" + link.get("href", ""),
                            (img.get("data-src") or img.get("src")) if img else ""))
    return out


def amazon(q):
    r = requests.get(f"https://www.amazon.eg/s?k={quote_plus(q)}", headers=HEADERS, timeout=15)
    if "captcha" in r.text.lower():
        raise RuntimeError("blocked by captcha")
    soup, out = BeautifulSoup(r.text, "html.parser"), []
    for c in soup.select('div[data-component-type="s-search-result"]'):
        t, p = c.select_one("h2"), c.select_one("span.a-price span.a-offscreen")
        a, img = c.select_one("h2 a") or c.select_one("a.a-link-normal"), c.select_one("img.s-image")
        if t and p and a:
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
    r = requests.get(f"https://www.noon.com/egypt-en/search/?q={quote_plus(q)}", headers=HEADERS, timeout=8)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
    if not m:
        raise RuntimeError("blocked or page changed")
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
    """Brand sites + Egyptian shops (often includes Noon/Amazon listings). Needs SERPAPI_KEY."""
    key = os.getenv("SERPAPI_KEY")
    if not key:
        raise RuntimeError("SERPAPI_KEY is missing")
    # tell Google to skip accessories
    negatives = [f"-{w}" for w in ("case", "cover", "protector") if w not in q.lower()]
    r = requests.get("https://serpapi.com/search.json", timeout=25, params={
        "engine": "google_shopping", "q": " ".join([q] + negatives), "gl": "eg", "hl": "en",
        "google_domain": "google.com.eg", "api_key": key})
    data = r.json()
    if data.get("error") and "hasn't returned any results" not in data["error"]:
        raise RuntimeError(data["error"])
    out = []
    for s in data.get("shopping_results", []):
        link = s.get("product_link") or s.get("link")
        price = s.get("extracted_price")
        if link and price:
            out.append(_row(s.get("source", "Web"), s.get("title"), float(price), link, s.get("thumbnail")))
    return out


SOURCES = {"Jumia": jumia, "Amazon.eg": amazon, "Google Shopping": google_shopping, "Noon (often blocked)": noon}
DEFAULT_SOURCES = ["Jumia", "Amazon.eg", "Google Shopping"]


# ---------------------------------------------------------------- filtering
def _tokens(s):
    return re.findall(r"[\w+/]+", s.lower())


def _matches_item(item, title):
    """Every number/model token must match; plus at least 60% of all words."""
    words = [w for w in re.findall(r"\w+", item.lower()) if len(w) > 1]
    t = title.lower()
    if not words:
        return True
    hits = 0
    for w in words:
        pat = rf"\b{re.escape(w)}\b" if w.isdigit() else rf"\b{re.escape(w)}"
        found = re.search(pat, t) is not None
        if any(c.isdigit() for c in w) and not found:
            return False                      # model numbers must match
        hits += found
    return hits / len(words) >= 0.6


def _is_accessory(item, title):
    q = set(_tokens(item))
    toks = _tokens(title)
    for i, w in enumerate(toks):
        if w in ACCESSORY_WORDS and w not in q:
            prev = toks[i - 1] if i else ""
            if prev not in BUNDLE_WORDS:      # "with charger" is fine
                return True
    return False


def filter_rows(spec, rows):
    item = spec["name"]
    excl = [e.strip().lower() for e in spec.get("exclude", []) if e.strip()]
    mn = spec.get("min_price") or 0
    keep = []
    for r in rows:
        t = r["title"].lower()
        if not r["price"] or r["price"] < mn:
            continue
        if not _matches_item(item, r["title"]) or _is_accessory(item, r["title"]):
            continue
        if any(e in t for e in excl):
            continue
        keep.append(r)
    # price sanity: drop anything far below the typical price (usually accessories / fakes)
    if not mn and len(keep) >= 4:
        med = statistics.median(r["price"] for r in keep)
        keep = [r for r in keep if r["price"] >= 0.3 * med]
    return keep


# ---------------------------------------------------------------- search
def search_item(spec, keywords=(), sources=None, top=5):
    """spec: {"name","min_price","max_price","exclude"}. Returns {"rows","errors","stats"}."""
    sources = sources or DEFAULT_SOURCES
    item = spec["name"]
    queries = [(item, "")] + [(f"{item} {k}", k) for k in keywords if k.strip()]
    jobs = [(s, q, tag) for s in sources for q, tag in queries]
    errors, stats = [], {s: {"found": 0, "kept": 0} for s in sources}

    def run(job):
        s, q, tag = job
        try:
            rows = SOURCES[s](q)
            return [dict(r, tag=tag, src=s) for r in rows]
        except Exception as e:
            errors.append(f"{s}: {str(e)[:120]}")
            return []

    allrows = []
    with ThreadPoolExecutor(8) as ex:
        for rows in ex.map(run, jobs):
            allrows += rows
    for r in allrows:
        stats[r["src"]]["found"] += 1
    unique = {}
    for r in filter_rows(spec, allrows):
        old = unique.get(r["link"])
        if not old or (r["tag"] and not old["tag"]):
            unique[r["link"]] = r
    ranked = sorted(unique.values(), key=lambda r: r["price"])
    for r in ranked:
        stats[r["src"]]["kept"] += 1
    return {"rows": ranked[:top], "errors": sorted(set(errors)), "stats": stats}


def search_many(specs, keywords=(), sources=None, top=5):
    with ThreadPoolExecutor(3) as ex:
        outs = list(ex.map(lambda s: search_item(s, keywords, sources, top), specs))
    return {s["name"]: o for s, o in zip(specs, outs)}
