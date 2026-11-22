"""Singapore Food Agency (SFA): food recalls of products from China.

Singapore does not publish rejected import consignments, only recalls of products already on
the market. SFA's newsroom has a public JSON API. Recall articles are free text, so Claude reads
each article and returns the products in it; we keep products whose country of origin is
mainland China. Product photos on the page go through the normal image review (admin page).
"""
import datetime as dt
import html
import json
import re
import time

import requests

from . import mt

BASE = "https://www.sfa.gov.sg"
API = BASE + "/api/newsroom/search"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0 Safari/537.36"}
class Blocked(Exception):
    """SFA's firewall answers cloud servers (such as GitHub's) with an empty 202 page."""


RECALL = re.compile(r"recall|adulterat|found to contain|not permitted|unsafe|contaminat", re.I)


def articles(since):
    """Newsroom items published on or after since that look like recalls, newest first."""
    out, page = [], 1
    while True:
        r = requests.get(API, params={"page": page, "limit": 100, "contentTypes": "12,15,16,13,17,14"},
                         headers=UA, timeout=60)
        r.raise_for_status()
        if r.status_code == 202 or not r.content:
            raise Blocked("SFA site blocked this server (HTTP 202, empty page)")
        d = r.json()
        items = [i for i in d.get("items") or [] if i.get("lastPublished")]
        out += [i for i in items if i["lastPublished"][:10] >= since and RECALL.search(i.get("title") or "")]
        oldest = min((i["lastPublished"][:10] for i in items), default="")
        if page >= (d.get("totalPages") or 1) or not items or oldest < since:
            return out
        page += 1


def article_text(url):
    r = requests.get(BASE + url, headers=UA, timeout=60)
    r.raise_for_status()
    m = re.search(r"<main\b.*?</main>", r.text, re.S)
    part = re.sub(r"<script.*?</script>|<style.*?</style>", "", m.group(0) if m else r.text, flags=re.S)
    part = re.sub(r"<(br|/p|/li|/h\d|/tr|/div)\b[^>]*>", "\n", part)
    txt = html.unescape(re.sub(r"<[^>]+>", " ", part))
    txt = re.sub(r"[ \t]+", " ", txt)
    return re.sub(r"\n\s*\n+", "\n", txt).strip()[:9000]


PROMPT = """This is a food recall or food safety article from the Singapore Food Agency.
List every product named in it. For each product return:
- name_en: product name as written (with pack size)
- name_zh: short natural Simplified Chinese name as used in mainland China; keep the brand in its original form
- brand: brand if stated, else ""
- origin: country of origin as stated in the title or the article (for example "from China" in the title), else "" (do not guess)
- importer: importer or distributor in Singapore if stated, else ""
- batch: batch number, production date, best before or expiry details if stated, else ""
- reason_zh: why it is recalled, in Simplified Chinese, keeping numbers, units and substances; do not add information
- types: one or more of: {types}
- withdrawn: true only if this article says an earlier recall or finding for this product was wrong
  (for example a false positive) or the recall was lifted; otherwise false
- withdrawn_zh: if withdrawn, a short Chinese explanation of why (for example 检测方法导致假阳性，产品已恢复销售), else ""

Return only JSON: {{"products": [...]}}. If the article names no product, return {{"products": []}}.

Title: {title}

Article:
{text}"""


def extract(title, text):
    types = "、".join(mt.PROBLEM_TYPES)
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": mt.API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": mt.MODEL, "max_tokens": 4000,
              "messages": [{"role": "user", "content": PROMPT.format(types=types, title=title, text=text)}]},
        timeout=180,
    )
    r.raise_for_status()
    out = "".join(c.get("text", "") for c in r.json().get("content", []))
    m = re.search(r"\{.*\}", out, re.S)
    try:
        return (json.loads(m.group(0)) if m else {}).get("products") or []
    except ValueError:
        return []


def is_china(origin):
    o = (origin or "").lower()
    return "china" in o and not any(x in o for x in ("taiwan", "hong kong", "macau", "macao"))


def key(p):
    """Product name for matching follow-up articles to earlier ones."""
    n = (p.get("name_en") or p.get("name_zh") or "").lower()  # English is copied from the article, so it is stable
    n = re.sub(r"[（(].*?[)）]|\d+\s*(g|kg|ml|l|克|千克|毫升|升)\b|\b(products?|prepacked|brand|of|the)\b", "", n)
    return re.sub(r"[\s\W_]+", "", n)


def fetch(since, known=(), delay=0.5):
    """[(article, [(index, product)])] oldest first, products from China only. Needs the Claude key.
    known: names (see key()) of Chinese products stored earlier, so follow-ups without an origin still match."""
    if not mt.available():
        return []
    known = set(known)
    out = []
    for a in sorted(articles(since), key=lambda x: x["lastPublished"]):
        text = article_text(a["url"])
        prods = extract(a["title"], text)
        keep = []
        for i, p in enumerate(prods):
            if not isinstance(p, dict):
                continue
            k = key(p)
            if is_china(p.get("origin")) or (not p.get("origin") and k and k in known):
                known.add(k)
                keep.append((i, p))
        if keep:
            out.append((a, keep))
        time.sleep(delay)
    return out


def normalize(a, i, p):
    slug = a["url"].rstrip("/").split("/")[-1][:80]
    note = []
    if p.get("batch"):
        note.append("批次/日期：" + p["batch"])
    note.append("原产国：中国")
    types = [t for t in (p.get("types") or []) if t in mt.PROBLEM_TYPES] or ["其他"]
    return {
        "id": f"SFA-{slug}-{i}", "src": "SFA", "pub_date": a["lastPublished"][:10], "insp_date": None,
        "grp": "食品", "ind": "", "ntype": "市场召回",
        "product": p.get("name_zh") or p.get("name_en") or "", "product_orig": p.get("name_en") or "",
        "problems": list(dict.fromkeys(types)), "detail": p.get("reason_zh") or "", "legal_limit": "",
        "quantity": "", "firm": p.get("brand") or "", "importer": p.get("importer") or "",
        "lab_tested": bool(re.search(r"检出|检测|超标|超过", p.get("reason_zh") or "")), "entry_no": "", "action": "召回", "note": "；".join(note),
        "url": BASE + a["url"], "raw": {"article": a, "product": p}, "machine_translated": True,
    }
