"""Price Hunter v3 - Google-style fuzzy price search.
Main engine: Google Shopping via Serper.dev (reliable). Bonus: direct Jumia / Amazon.eg / Noon."""
import json, os, re, statistics, time
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup

UAS = [
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]
ACCESSORY_WORDS = {
    "case", "cases", "cover", "covers", "protector", "protectors", "tempered", "skin", "holder",
    "stand", "pouch", "sleeve", "film", "sticker", "stickers", "strap", "straps", "charger",
    "cable", "adapter", "جراب", "كفر", "غطاء", "حماية", "اسكرينة", "سكرينة", "شاحن", "كابل", "استيك",
}
BUNDLE_WORDS = {"with", "including", "free", "plus", "and", "+", "w/", "مع"}
SHOP_DOMAINS = ("noon.com", "amazon.eg", "jumia.com.eg")


def _num(text):
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(text or ""))
    return float(m.group().replace(",", "")) if m else None


def _row(store, title, price, link, image="", note=""):
    return {"store": store, "title": (title or "").strip(), "price": price, "currency": "EGP",
            "link": link, "image": image or "", "tag": "", "src": "", "note": note, "score": 0.0}


def _get(url, timeout=12, tries=3):
    """Fetch with retries and different browser identities (shops randomly block servers)."""
    last = None
    for n in range(tries):
        try:
            r = requests.get(url, timeout=timeout, headers={
                "User-Agent": UAS[n % len(UAS)], "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
                "Accept": "text/html,application/xhtml+xml"})
            if r.status_code == 200 and len(r.text) > 5000 and "captcha" not in r.text[:20000].lower():
                return r
            last = f"HTTP {r.status_code} / challenge page"
        except Exception as e:
            last = type(e).__name__
        time.sleep(1)
    raise RuntimeError(f"blocked ({last})")


# ------------------------------------------------------------ Google-based engines (reliable)
def _serper(endpoint, q):
    key = os.getenv("SERPER_API_KEY")
    if not key:
        raise RuntimeError("SERPER_API_KEY is missing")
    r = requests.post(f"https://google.serper.dev/{endpoint}", timeout=25,
                      headers={"X-API-KEY": key, "Content-Type": "application/json"},
                      json={"q": q, "gl": "eg", "hl": "en"})
    if r.status_code in (401, 403):
        raise RuntimeError("Serper key rejected")
    r.raise_for_status()
    return r.json()


def google_shopping(q):
    if os.getenv("SERPER_API_KEY"):
        data = _serper("shopping", q)
        return [_row(s.get("source", "Web"), s.get("title"), _num(s.get("price")), s.get("link"),
                     s.get("imageUrl"))
                for s in data.get("shopping", []) if s.get("link")]
    key = os.getenv("SERPAPI_KEY")           # fallback engine
    if not key:
        raise RuntimeError("no Serper/SerpAPI key")
    d = requests.get("https://serpapi.com/search.json", timeout=25, params={
        "engine": "google_shopping", "q": q, "gl": "eg", "hl": "en",
        "google_domain": "google.com.eg", "api_key": key}).json()
    if d.get("error") and "hasn't returned any results" not in d["error"]:
        raise RuntimeError(d["error"][:100])
    return [_row(s.get("source", "Web"), s.get("title"), s.get("extracted_price"),
                 s.get("product_link") or s.get("link"), s.get("thumbnail"))
            for s in d.get("shopping_results", []) if s.get("product_link") or s.get("link")]


def google_web(q):
    """Google results from Noon / Amazon.eg / Jumia pages (price taken from the snippet when shown)."""
    data = _serper("search", f"{q} (site:noon.com OR site:amazon.eg OR site:jumia.com.eg)")
    out = []
    for o in data.get("organic", []):
        link, host = o.get("link", ""), urlparse(o.get("link", "")).netloc
        store = next((d for d in SHOP_DOMAINS if d in host), None)
        if not store:
            continue
        text = f"{o.get('title','')} {o.get('snippet','')}"
        m = re.search(r"(?:EGP|E£|LE|جنيه|ج\.م)\s?([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s?(?:EGP|E£|جنيه|ج\.م)", text)
        price = _num(m.group(1) or m.group(2)) if m else None
        out.append(_row(store, o.get("title"), price, link, "", "price from search snippet" if price else ""))
    return out


# ------------------------------------------------------------ direct shop scrapers (bonus, may be blocked)
def jumia(q):
    soup = BeautifulSoup(_get(f"https://www.jumia.com.eg/catalog/?q={quote_plus(q)}").text, "html.parser")
    out = []
    for a in soup.select("article.prd"):
        link, name, prc, img = a.select_one("a.core"), a.select_one(".name"), a.select_one(".prc"), a.select_one("img")
        if link and name and prc:
            out.append(_row("Jumia", name.text, _num(prc.text), "https://www.jumia.com.eg" + link.get("href", ""),
                            (img.get("data-src") or img.get("src")) if img else ""))
    return out


def amazon(q):
    soup = BeautifulSoup(_get(f"https://www.amazon.eg/s?k={quote_plus(q)}").text, "html.parser")
    out = []
    for c in soup.select("div[data-asin]"):
        if not c.get("data-asin"):
            continue
        t, p = c.select_one("h2"), c.select_one("span.a-price span.a-offscreen")
        a, img = c.select_one("h2 a") or c.select_one("a.a-link-normal"), c.select_one("img.s-image")
        if t and p and a:
            out.append(_row("Amazon.eg", t.text, _num(p.text),
                            "https://www.amazon.eg" + a.get("href", "").split("?")[0], img.get("src") if img else ""))
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
    r = _get(f"https://www.noon.com/egypt-en/search/?q={quote_plus(q)}", timeout=8, tries=2)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
    if not m:
        raise RuntimeError("blocked or page changed")
    out, seen = [], set()
    for d in _walk(json.loads(m.group(1))):
        if d.get("name") and d.get("sku") and d.get("url") and (d.get("sale_price") or d.get("price")):
            if d["sku"] not in seen:
                seen.add(d["sku"])
                img = f"https://f.nooncdn.com/p/{d['image_key']}.jpg" if d.get("image_key") else ""
                out.append(_row("Noon", d["name"], _num(d.get("sale_price") or d.get("price")),
                                f"https://www.noon.com/egypt-en/{d['url']}/{d['sku']}/p/", img))
    return out


SOURCES = {
    "Google Shopping": google_shopping,
    "Google links (Noon/Amazon/Jumia pages)": google_web,
    "Jumia (direct)": jumia,
    "Amazon.eg (direct)": amazon,
    "Noon (direct, usually blocked)": noon,
}
DEFAULT_SOURCES = ["Google Shopping", "Google links (Noon/Amazon/Jumia pages)", "Jumia (direct)", "Amazon.eg (direct)"]


# ------------------------------------------------------------ fuzzy relevance
def _toks(s):
    return [t for t in re.findall(r"[\w]+", s.lower()) if len(t) > 1]


def _sim(a, b):
    if a == b:
        return 1.0
    if len(a) >= 3 and (b.startswith(a) or a.startswith(b)):
        return 0.9
    r = SequenceMatcher(None, a, b).ratio()
    return r if r >= 0.75 else 0.0


def relevance(item, title):
    q, t = _toks(item), _toks(title)
    if not q or not t:
        return 0.0
    return sum(max(_sim(w, x) for x in t) for w in q) / len(q)


def is_accessory(item, title):
    qset, toks = set(_toks(item)), re.findall(r"[\w+/]+", title.lower())
    return any(w in ACCESSORY_WORDS and w not in qset and (toks[i - 1] if i else "") not in BUNDLE_WORDS
               for i, w in enumerate(toks))


def variants(item, wide=True):
    vs = [item]
    if wide:
        swap = {"malay": "mlay", "mlay": "malay"}
        words = item.split()
        vs.append(" ".join(swap.get(w.lower(), w) for w in words))
        if len(words) > 2:
            vs.append(" ".join(words[:-1]))
    seen, out = set(), []
    for v in vs:
        if v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out[:3]


def classify(spec, rows):
    """Nothing is thrown away silently: rows go to best / related / links / other."""
    item = spec["name"]
    excl = [e.strip().lower() for e in spec.get("exclude", []) if e and e.strip()]
    mn = spec.get("min_price") or 0
    best, related, links, other = [], [], [], []
    for r in rows:
        r["score"] = relevance(item, r["title"])
        t = r["title"].lower()
        if r["score"] < 0.35 or any(e in t for e in excl):
            continue
        if r["price"] is None:
            links.append(r)
        elif r["price"] < mn:
            continue
        elif is_accessory(item, r["title"]):
            other.append(r)
        elif r["score"] >= 0.7:
            best.append(r)
        else:
            related.append(r)
    pool = best + related
    if not mn and len(pool) >= 4:                # far-too-cheap items are probably accessories
        med = statistics.median(r["price"] for r in pool)
        low = [r for r in pool if r["price"] < 0.3 * med]
        best = [r for r in best if r not in low]
        related = [r for r in related if r not in low]
        other += low
    key = lambda r: r["price"]
    return sorted(best, key=key), sorted(related, key=key), links, sorted(other, key=key)


# ------------------------------------------------------------ search
def search_item(spec, keywords=(), sources=None, top=6, wide=True):
    sources = sources or DEFAULT_SOURCES
    qs = [(v, "") for v in variants(spec["name"], wide)]
    qs += [(f"{spec['name']} {k}", k) for k in keywords if k.strip()]
    jobs = [(s, q, tag) for s in sources for q, tag in qs]
    errors, stats = [], {s: {"found": 0, "kept": 0} for s in sources}

    def run(job):
        s, q, tag = job
        try:
            return [dict(r, tag=tag, src=s) for r in SOURCES[s](q)]
        except Exception as e:
            errors.append(f"{s}: {str(e)[:110]}")
            return []

    with ThreadPoolExecutor(8) as ex:
        allrows = [r for rows in ex.map(run, jobs) for r in rows]
    uniq = {}
    for r in allrows:
        stats[r["src"]]["found"] += 1
        old = uniq.get(r["link"])
        if not old or (r["tag"] and not old["tag"]) or (old["price"] is None and r["price"]):
            uniq[r["link"]] = r
    best, related, links, other = classify(spec, list(uniq.values()))
    for r in best + related:
        stats[r["src"]]["kept"] += 1
    return {"best": best[:top], "related": related[:top], "links": links[:top], "other": other[:top],
            "errors": sorted(set(errors)), "stats": stats}


def search_many(specs, keywords=(), sources=None, top=6, wide=True):
    with ThreadPoolExecutor(3) as ex:
        outs = list(ex.map(lambda s: search_item(s, keywords, sources, top, wide), specs))
    return {s["name"]: o for s, o in zip(specs, outs)}
