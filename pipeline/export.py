"""Write the JSON files the website reads: data/meta.json and one data/<year>.json per year."""
import json
import os
from collections import defaultdict
from datetime import date

from . import db

SOURCES = {
    "TW": {"name": "台湾 食品药物管理署 (TFDA)", "url": "https://www.fda.gov.tw/UnsafeFood/UnsafeFood.aspx"},
    "US": {"name": "美国 FDA 进口拒收", "url": "https://datadashboard.fda.gov/oii/cd/imprefusals.htm"},
}


def short(r):
    """Short keys keep the files small."""
    return {"id": r["id"], "src": r["src"], "d": r["pub_date"], "grp": r["grp"], "ind": r.get("ind") or "",
            "p": r.get("product") or "", "p0": r.get("product_orig") or "", "prob": r.get("problems") or [],
            "x": r.get("detail") or "", "lim": r.get("legal_limit") or "", "q": r.get("quantity") or "",
            "f": r.get("firm") or "", "imp": r.get("importer") or "", "lab": bool(r.get("lab_tested")),
            "e": r.get("entry_no") or "", "act": r.get("action") or "", "u": r.get("url") or ""}


def run(out_dir):
    cols = "id,src,pub_date,grp,ind,product,product_orig,problems,detail,legal_limit,quantity,firm,importer,lab_tested,entry_no,action,url"
    rows = db.fetch_all(cols)
    by_year = defaultdict(list)
    for r in rows:
        by_year[str(r["pub_date"])[:4]].append(short(r))
    os.makedirs(os.path.join(out_dir, "data"), exist_ok=True)
    years = sorted(by_year, reverse=True)
    for y in years:
        with open(os.path.join(out_dir, "data", f"{y}.json"), "w", encoding="utf-8") as f:
            json.dump(by_year[y], f, ensure_ascii=False, separators=(",", ":"))
    meta = {
        "built": date.today().isoformat(),
        "from": min(str(r["pub_date"]) for r in rows), "to": max(str(r["pub_date"]) for r in rows),
        "years": {y: len(by_year[y]) for y in years}, "sources": SOURCES,
    }
    with open(os.path.join(out_dir, "data", "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(f"exported {len(rows)} records in {len(years)} year files")
