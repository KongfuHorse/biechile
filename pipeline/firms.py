"""AI candidate Chinese names for Chinese firms (all sources since v2; the FDA-only v1 is kept below).

These are guesses that only help a person search Chinese business registries.
They are shown only in the admin page (table firm_candidates) and never on the public site.
A Chinese name appears on the site only after a person saves it as verified (table firm_names).
"""
import json
import os
import re

import requests

from . import db, mt, sources

PROMPT = (
    "Each item below is a company in mainland China, with the English name and English address it uses "
    "with the US FDA. For each company, suggest up to 3 possible Chinese legal company names (中文全称) "
    "that a person could type into a Chinese business registry search to find the real company. "
    "These are search guesses, not facts. Base them only on the English name and address "
    "(pinyin of place names, brand words, the type of company). For each guess give a very short reason "
    "in Chinese. If you cannot make a reasonable guess, return an empty list for that company.\n\n"
    "Return only a JSON object: {\"<fei>\": [{\"name\": \"...\", \"reason\": \"...\"}]}. No other text.\n\n"
)


def fda_address(fei):
    """English address the firm has in FDA data."""
    headers = {"Content-Type": "application/json",
               "Authorization-User": os.environ["FDA_USER"], "Authorization-Key": os.environ["FDA_KEY"]}
    body = {"start": 1, "rows": 1, "sort": "RefusalDate", "sortorder": "DESC",
            "filters": {"FEINumber": [fei]},
            "columns": ["FirmName", "AddressLine1", "AddressLine2", "City", "State", "ZipCode", "CountryName"]}
    r = requests.post(sources.FDA_URL, json=body, headers=headers, timeout=60)
    r.raise_for_status()
    res = (r.json() or {}).get("result") or []
    if not res:
        return ""
    a = res[0]
    return ", ".join(x for x in [a.get("AddressLine1"), a.get("AddressLine2"), a.get("City"),
                                  a.get("State"), a.get("ZipCode"), a.get("CountryName")] if x)


def ask_claude(items):
    """items: [{fei, firm_en, address}] -> {fei: [{name, reason}]}"""
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": mt.API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": mt.MODEL, "max_tokens": 3000,
              "messages": [{"role": "user", "content": PROMPT + json.dumps(items, ensure_ascii=False)}]},
        timeout=120,
    )
    r.raise_for_status()
    text = "".join(c.get("text", "") for c in r.json().get("content", []))
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {}


def generate_candidates(limit=20):
    """Make candidates for the most-refused firms that have no verified name and no candidates yet."""
    if not (db.using_supabase() and mt.available()):
        return 0
    top = db.fetch_table("firm_stats", "fei,firm_en,city", "&order=lines.desc&limit=300")
    have = {x["fei"] for x in db.fetch_table("firm_names", "fei", "&order=fei")} | \
           {x["fei"] for x in db.fetch_table("firm_candidates", "fei", "&order=fei")}
    todo = [f for f in top if f["fei"] not in have][:limit]
    if not todo:
        return 0
    items = []
    for f in todo:
        try:
            addr = fda_address(f["fei"])
        except requests.RequestException:
            addr = f.get("city") or ""
        items.append({"fei": f["fei"], "firm_en": f["firm_en"], "address": addr})
    rows = []
    for i in range(0, len(items), 10):
        batch = items[i:i + 10]
        got = ask_claude(batch)
        for it in batch:
            cands = [c for c in (got.get(it["fei"]) or []) if isinstance(c, dict) and c.get("name")][:3]
            rows.append({"fei": it["fei"], "firm_en": it["firm_en"], "address": it["address"],
                         "candidates": cands, "model": mt.MODEL})
    r = requests.post(f"{db.URL}/rest/v1/firm_candidates?on_conflict=fei", json=rows,
                      headers=db._h({"Prefer": "resolution=merge-duplicates,return=minimal"}), timeout=60)
    r.raise_for_status()
    return len(rows)


# ---------- v2: all sources, keyed by the merged English name (same rule as the site's firm ranking) ----------

KNOW_MODEL = os.environ.get("FIRM_AI_MODEL", "claude-sonnet-5-5")

PROMPT2 = (
    "Each item below is a company in mainland China, with the English name it uses with foreign food and "
    "product-safety regulators, the city if known, and recent products. For each company give up to 3 Chinese "
    "legal names (中文全称).\n"
    "Mark each name with basis:\n"
    "- \"known\": you actually know this specific real company and its Chinese name (for example a listed "
    "company, a well-known manufacturer or brand). Do not mark a name as known because the pinyin fits.\n"
    "- \"guess\": a reasoned guess from pinyin, meaning and place names, to help a person search a Chinese "
    "business registry.\n"
    "Give a very short reason in Chinese for each name. If you cannot make a reasonable guess, return an empty "
    "list. Return only a JSON object: {\"<id>\": [{\"name\": \"...\", \"basis\": \"known|guess\", "
    "\"reason\": \"...\"}]}. No other text.\n\n"
)


def firm_key(name):
    """Same as SQL firm_key() and the site's firmKey()."""
    s = re.sub(r"[.,()（）\"“”'’]", " ", (name or "").upper())
    s = re.sub(r"\bCOMPANY\b", "CO", s)
    s = re.sub(r"\bLIMITED\b", "LTD", s)
    s = re.sub(r"\bCORPORATION\b", "CORP", s)
    # spaces, hyphens and "&" vary between notices of the same firm ("GUANG DONG"/"GUANGDONG", "M & C"/"M AND C")
    return re.sub(r"[\s\-‐–—_/\\·•+:;!?#*~|]", "", s.replace("&", " AND "))


def _ask(items, model):
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": mt.API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": model, "max_tokens": 6000,
              "messages": [{"role": "user", "content": PROMPT2 + json.dumps(items, ensure_ascii=False)}]},
        timeout=300,
    )
    r.raise_for_status()
    text = "".join(c.get("text", "") for c in r.json().get("content", []))
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}


def generate_candidates2(limit=60, model=None):
    """AI names for the most-notified firms that have no verified name and no AI names yet."""
    if not (db.using_supabase() and mt.available()) or limit <= 0:
        return 0
    model = model or KNOW_MODEL
    have = {x["firm_key"] for x in db.fetch_table("firm_zh", "firm_key", "&order=firm_key")} | \
           {x["firm_key"] for x in db.fetch_table("firm_ai", "firm_key", "&order=firm_key")}
    top = db.fetch_table("firm_all", "firm_key,firm_en,city,last_product,sources,n",
                         f"&order=n.desc,firm_key.asc&limit={limit + len(have) + 50}")
    todo = [f for f in top if f["firm_key"] not in have][:limit]
    done = 0
    for i in range(0, len(todo), 15):
        batch = todo[i:i + 15]
        items = {str(j + 1): {"name": f["firm_en"], "city": f.get("city") or "", "products": f.get("last_product") or ""}
                 for j, f in enumerate(batch)}
        got = _ask(items, model)
        rows = []
        for j, f in enumerate(batch):
            cands = [c for c in (got.get(str(j + 1)) or []) if isinstance(c, dict) and c.get("name")][:3]
            for c in cands:
                c["basis"] = "known" if c.get("basis") == "known" else "guess"
            rows.append({"firm_key": f["firm_key"], "firm_en": f["firm_en"], "candidates": cands, "model": model})
        r = requests.post(f"{db.URL}/rest/v1/firm_ai?on_conflict=firm_key", json=rows,
                          headers=db._h({"Prefer": "resolution=merge-duplicates,return=minimal"}), timeout=60)
        r.raise_for_status()
        done += len(rows)
        print(f"  firm names: {done}/{len(todo)}", flush=True)
    return done
