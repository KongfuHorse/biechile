"""Write the JSON files the website reads: data/meta.json and one data/<year>.json per year."""
import json
import os
import re
from collections import defaultdict
from datetime import date

from . import db, normalize

SOURCES = {
    "TW": {"name": "台湾 食品药物管理署 (TFDA)", "url": "https://www.fda.gov.tw/UnsafeFood/UnsafeFood.aspx"},
    "US": {"name": "美国 FDA 进口拒收", "url": "https://datadashboard.fda.gov/oii/cd/imprefusals.htm"},
}


def apply_reviews(r, tt, firm_zh):
    """Use the latest reviewed translations and verified Chinese firm names.
    tt: {(kind, source): (zh, status)} from term_translations. Static reference tables always win."""
    raw = r.get("raw") or {}
    fei = r.get("fei") or raw.get("FEINumber") or ""
    r["firm_zh"] = firm_zh.get(fei, "") if r.get("src") == "US" else ""
    if r.get("src") != "US" or not tt:
        return r
    machine = False
    po = r.get("product_orig") or ""
    if po not in normalize._fda_product_zh and ("fda_product", po) in tt:
        zh, st = tt[("fda_product", po)]
        r["product"] = zh; machine |= st == "machine"
    io = r.get("ind0") or raw.get("IndustryCodeDescription") or ""
    if io not in normalize.IND_ZH and ("fda_industry", io) in tt:
        zh, st = tt[("fda_industry", io)]
        r["ind"] = zh; machine |= st == "machine"
    parts = []
    for part in (r.get("detail") or "").split("；"):
        m = re.match(r"^(.*) \[(.+)\]$", part)
        if m and m.group(2) not in normalize.FDA_CODE and ("fda_code", m.group(2)) in tt:
            zh, st = tt[("fda_code", m.group(2))]
            part = f"{zh} [{m.group(2)}]"; machine |= st == "machine"
        parts.append(part)
    r["detail"] = "；".join(parts)
    r["machine_translated"] = machine
    return r


def short(r):
    """Short keys keep the files small."""
    return {"id": r["id"], "src": r["src"], "d": r["pub_date"], "grp": r["grp"], "ind": r.get("ind") or "",
            "p": r.get("product") or "", "p0": r.get("product_orig") or "", "prob": r.get("problems") or [],
            "x": r.get("detail") or "", "lim": r.get("legal_limit") or "", "q": r.get("quantity") or "",
            "f": r.get("firm") or "", "imp": r.get("importer") or "", "lab": bool(r.get("lab_tested")),
            "e": r.get("entry_no") or "", "act": r.get("action") or "", "u": r.get("url") or "",
            "mt": bool(r.get("machine_translated")), "fz": r.get("firm_zh") or ""}


def run(out_dir):
    cols = "id,src,pub_date,grp,ind,product,product_orig,problems,detail,legal_limit,quantity,firm,importer,lab_tested,entry_no,action,url,machine_translated"
    cols += ",fei:raw->>FEINumber,ind0:raw->>IndustryCodeDescription"
    rows = db.fetch_all(cols)
    tt = {(t["kind"], t["source"]): (t["zh"], t["status"])
          for t in db.fetch_table("term_translations", "kind,source,zh,status")}
    firm_zh = {f["fei"]: f["zh_name"] for f in db.fetch_table("firm_names", "fei,zh_name")}
    rows = [apply_reviews(r, tt, firm_zh) for r in rows]
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
