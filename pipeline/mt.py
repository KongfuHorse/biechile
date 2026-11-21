"""Machine translation for new terms that are not in the reference tables yet.

Only terms missing from ref/ files are sent to Claude (Haiku). Results are saved in the
Supabase table term_translations with status 'machine', so each term is translated once.
Records that use a machine translation get machine_translated = true and show a "机翻" tag
on the website until a person checks the term and sets status = 'verified'.
"""
import json
import os
import re

import requests

from . import db

MODEL = "claude-haiku-5-5"
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

STYLE = {
    "fda_product": (
        "These are US FDA product code descriptions for products imported from China. "
        "Translate each into short, natural Simplified Chinese as used in mainland China. "
        "Keep it close to the original meaning. Do not add information that is not in the English "
        "(for example, do not add cooking methods). Drop FDA filler words like 'N.E.C.' but keep the idea "
        "as '（其他）'. Use standard mainland Chinese names for drugs, devices and species."
    ),
    "fda_industry": (
        "These are US FDA industry category names. Translate each into a short Simplified Chinese category name."
    ),
    "fda_code": (
        "These are US FDA import refusal charge statements. Translate each into one short Simplified Chinese "
        "phrase (under 20 characters) that says what was wrong with the product."
    ),
}


def available():
    return bool(API_KEY)


def _examples(kind, ref, n=25):
    items = list(ref.items())[:: max(1, len(ref) // n)][:n]
    return "\n".join(f"{k} => {v}" for k, v in items)


def translate(kind, terms, ref_examples):
    """Translate a list of English terms. Returns {term: zh}."""
    if not terms or not available():
        return {}
    out = {}
    for i in range(0, len(terms), 40):
        batch = terms[i:i + 40]
        prompt = (
            f"{STYLE[kind]}\n\nExamples of the style to follow:\n{_examples(kind, ref_examples)}\n\n"
            "Return only a JSON object that maps each input string exactly as given to its translation. "
            "No other text.\n\nInput:\n" + json.dumps(batch, ensure_ascii=False)
        )
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": MODEL, "max_tokens": 4000, "messages": [{"role": "user", "content": prompt}]},
            timeout=120,
        )
        r.raise_for_status()
        text = "".join(c.get("text", "") for c in r.json().get("content", []))
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            continue
        data = json.loads(m.group(0))
        out.update({k: v.strip() for k, v in data.items() if k in batch and isinstance(v, str) and v.strip()})
    return out


# ---------------- cache in Supabase (or a local file without Supabase) ----------------
LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "local_data", "term_translations.json")


def load_cache():
    """{kind: {source: zh}} for all saved machine and verified translations."""
    rows = []
    if db.using_supabase():
        r = requests.get(f"{db.URL}/rest/v1/term_translations?select=kind,source,zh", headers=db._h(), timeout=60)
        r.raise_for_status()
        rows = r.json()
    elif os.path.exists(LOCAL):
        rows = json.load(open(LOCAL, encoding="utf-8"))
    cache = {}
    for x in rows:
        cache.setdefault(x["kind"], {})[x["source"]] = x["zh"]
    return cache


def save(kind, mapping):
    rows = [{"kind": kind, "source": k, "zh": v, "model": MODEL, "status": "machine"} for k, v in mapping.items()]
    if not rows:
        return
    if db.using_supabase():
        r = requests.post(f"{db.URL}/rest/v1/term_translations?on_conflict=kind,source", json=rows,
                          headers=db._h({"Prefer": "resolution=ignore-duplicates,return=minimal"}), timeout=60)
        r.raise_for_status()
    else:
        old = json.load(open(LOCAL, encoding="utf-8")) if os.path.exists(LOCAL) else []
        os.makedirs(os.path.dirname(LOCAL), exist_ok=True)
        json.dump(old + rows, open(LOCAL, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
