"""Machine translation for new terms that are not in the reference tables yet.

Only terms missing from ref/ files are sent to Claude (Haiku). Results are saved in the
Supabase table term_translations with status 'machine', so each term is translated once.
Records that use a machine translation get machine_translated = true and show a "机翻" tag
on the website until a person checks the term and sets status = 'verified'.
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor
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
    for i in range(0, len(terms), 20):
        batch = terms[i:i + 20]
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
        try:
            data = json.loads(m.group(0)) if m else {}
        except ValueError:  # one bad line spoils the whole object: read the pairs one by one
            data = dict(re.findall(r'^\s*"(.+?)"\s*:\s*"(.*?)"\s*,?\s*$', text, re.M))
        # the model sometimes tidies spacing in the keys, so match on the key without extra spaces
        key = lambda t: re.sub(r"\s+", " ", t).strip().rstrip(",").upper()
        wanted = {key(t): t for t in batch}
        got = {wanted[key(k)]: v.strip() for k, v in data.items()
               if isinstance(k, str) and key(k) in wanted and isinstance(v, str) and v.strip()}
        if len(got) < len(batch):
            print(f"  translate {kind}: {len(got)}/{len(batch)} in batch {i // 20 + 1}; reply starts: {text[:200]!r}",
                  flush=True)
        out.update(got)
    return out


# ---------------- cache in Supabase (or a local file without Supabase) ----------------
LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "local_data", "term_translations.json")


def load_cache():
    """{kind: {source: zh}} for all saved machine and verified translations."""
    rows = []
    if db.using_supabase():
        rows = db.fetch_table("term_translations", "kind,source,zh", "&order=kind,source")
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


# ---------------- notices from Japan, EU and Korea: translate text and pick problem types ----------------
PROBLEM_TYPES = {
    "农药残留": "pesticide residues",
    "兽药残留": "veterinary drug residues, antibiotics in animal products",
    "污染物": "heavy metals, mycotoxins such as aflatoxin, dioxins, other contaminants, natural toxins",
    "微生物": "bacteria, Salmonella, Listeria, E. coli, coliforms, mould, viruses, parasites",
    "色素/添加剂": "food additives, colours, preservatives, sweeteners, sulphites, unauthorised additives",
    "材质/溶出": "food contact materials or toys: migration, formaldehyde, melamine, plastic or metal limits",
    "卫生/生产": "spoilage, foreign bodies, insects, poor hygiene, temperature control problems",
    "产品标准": "composition or quality standards not met, unauthorised novel food or ingredient, undeclared drug substance",
    "标签": "labelling, undeclared allergens",
    "手续/审批": "missing certificate, no health certificate, illegal import, documents",
    "其他": "none of the above",
}
NONFOOD_TYPES = {
    "化学有害物": "lead, phthalates, cadmium, banned chemicals, toxic substances",
    "窒息/勒颈": "choking on small parts, suffocation, strangulation, entanglement",
    "触电": "electric shock, electrocution",
    "火灾/烧伤": "fire, overheating, burns, scalds, battery fire",
    "受伤": "falls, tip-over, laceration, impact, entrapment, crushing, magnet ingestion, button battery ingestion",
    "溺水": "drowning",
    "视力/听力损伤": "damage to eyes or hearing",
    "环境危害": "environmental harm",
    "微生物": "bacteria, mould",
    "标签": "missing warnings or labels, instructions",
    "其他": "none of the above",
}
NONFOOD_SRCS = ("CPSC",)
SRC_LANG = {"JP": "Japanese (from Japan's Ministry of Health border inspection records)",
            "EU": "English or another EU language (from the EU RASFF food alert system)",
            "KR": "Korean (from Korea's Ministry of Food and Drug Safety import inspection records)",
            "AU": "English (from Australia's imported food inspection failing food reports; the problem text names the test and the substance found)",
            "CPSC": "English (from US Consumer Product Safety Commission recalls of consumer products; the problem text has the hazard, "
                    "incidents and where it was sold; translate all of it, starting each part on a new line)",
            "SG": "English (from the EU Safety Gate alert system for dangerous non-food products such as toys, "
                  "electrical appliances, cosmetics and children's products; the product field has the product type "
                  "and the product name, separated by |)"}


def translate_items(src, items):
    """items: [{"product": str, "detail": str}] in the source language.
    Returns {"product": {orig: zh}, "detail": {orig: zh}, "prob": {detail_orig: "type|type"}}."""
    out = {"product": {}, "detail": {}, "prob": {}}
    if not items or not available():
        return out
    type_dict = NONFOOD_TYPES if src in NONFOOD_SRCS else PROBLEM_TYPES
    types = "\n".join(f"- {k}: {v}" for k, v in type_dict.items())

    def one(batch):
        prompt = (
            f"Below are records of products from China that failed inspection or were found unsafe. The text is in {SRC_LANG[src]}.\n"
            "For each record:\n"
            "1. product_zh: translate the product name into short, natural Simplified Chinese as used in mainland China. "
            "Keep brand names and model numbers in their original form.\n"
            "2. detail_zh: translate the problem description into Simplified Chinese. Keep every number, unit and "
            "substance. Use standard mainland Chinese names for pesticides, drugs, chemicals and microbes. "
            "Do not add information that is not in the source. Say legal boilerplate briefly, for example "
            "'超过残留限量' instead of a long sentence that cites the article of the law. Translate the whole text: "
            "if it has a line starting with 'Description:', keep it as a new line starting with '产品描述：'.\n"
            "3. types: one or more problem types from this list (use the Chinese key exactly):\n" + types + "\n\n"
            "Return only a JSON array with one object per record, in the same order: "
            '[{"i": 0, "product_zh": "...", "detail_zh": "...", "types": ["..."]}]. No other text.\n\n'
            "Records:\n" + json.dumps([{"i": n, **x} for n, x in enumerate(batch)], ensure_ascii=False)
        )
        part = {"product": {}, "detail": {}, "prob": {}}
        for attempt in range(3):
            try:
                r = requests.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    json={"model": MODEL, "max_tokens": 12000, "messages": [{"role": "user", "content": prompt}]},
                    timeout=240,
                )
                if r.status_code in (429, 500, 502, 503, 529):
                    time.sleep(20 * (attempt + 1))
                    continue
                r.raise_for_status()
                break
            except requests.RequestException:
                if attempt == 2:
                    return part
                time.sleep(10)
        else:
            return part
        text = "".join(c.get("text", "") for c in r.json().get("content", []))
        m = re.search(r"\[.*\]", text, re.S)
        if not m:
            return part
        try:
            data = json.loads(m.group(0))
        except ValueError:
            return part
        for d in data:
            if not isinstance(d, dict) or not isinstance(d.get("i"), int) or not 0 <= d["i"] < len(batch):
                continue
            src_item = batch[d["i"]]
            if src_item.get("product") and (d.get("product_zh") or "").strip():
                part["product"][src_item["product"]] = d["product_zh"].strip()
            if src_item.get("detail") and (d.get("detail_zh") or "").strip():
                part["detail"][src_item["detail"]] = d["detail_zh"].strip()
                ts = [t for t in (d.get("types") or []) if t in type_dict]
                part["prob"][src_item["detail"]] = "|".join(dict.fromkeys(ts or ["其他"]))
        return part

    batches = [items[i:i + 15] for i in range(0, len(items), 15)]
    with ThreadPoolExecutor(max_workers=10) as ex:
        for part in ex.map(one, batches):
            for k in out:
                out[k].update(part[k])
    return out


def prepare(src, rows, get_product, get_detail, cache):
    """Translate what is not in cache yet, save it, and return a function row -> {product, detail, probs}.
    cache: {kind: {source: zh}} as returned by load_cache(); updated in place."""
    k = src.lower()
    kp, kd, kb = f"{k}_product", f"{k}_detail", f"{k}_prob"
    for kind in (kp, kd, kb):
        cache.setdefault(kind, {})
    todo, seen = [], set()
    for r in rows:
        p, d = get_product(r) or "", get_detail(r) or ""
        need_p = p and p not in cache[kp]
        need_d = d and (d not in cache[kd] or d not in cache[kb])
        if (need_p or need_d) and (p, d) not in seen:
            seen.add((p, d))
            todo.append({"product": p if need_p else "", "detail": d if need_d else ""})
    if todo and available():
        got = translate_items(src, todo)
        for kind, part in ((kp, "product"), (kd, "detail"), (kb, "prob")):
            save(kind, got[part])
            cache[kind].update(got[part])

    def tr(r):
        p, d = get_product(r) or "", get_detail(r) or ""
        probs = cache[kb].get(d)
        return {"product": cache[kp].get(p), "detail": cache[kd].get(d),
                "probs": probs.split("|") if probs else None}
    return tr
