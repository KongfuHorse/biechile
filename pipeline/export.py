"""Write the JSON files the website reads: data/meta.json and one data/<year>.json per year."""
import json
import os
import re
from collections import defaultdict
from datetime import date

from . import cn_site, db, firms, images, normalize

SOURCES = {
    "TW": {"name": "中国台湾 食品药物管理署 (TFDA)", "url": "https://www.fda.gov.tw/UnsafeFood/UnsafeFood.aspx"},
    "US": {"name": "美国 FDA 进口拒收", "url": "https://datadashboard.fda.gov/oii/cd/imprefusals.htm"},
    "JP": {"name": "日本 厚生劳动省 进口食品违反事例",
           "url": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/shokuhin/yunyu_kanshi/ihan/index.html"},
    "EU": {"name": "欧盟 食品和饲料快速预警系统 (RASFF)", "url": "https://webgate.ec.europa.eu/rasff-window/screen/search"},
    "KR": {"name": "韩国 食品医药品安全处 进口食品不合格", "url": "https://impfood.mfds.go.kr/CFCEE01F01"},
    "SG": {"name": "欧盟 非食品危险产品预警 (Safety Gate)", "url": "https://ec.europa.eu/safety-gate-alerts/screen/webReport"},
    "SFA": {"name": "新加坡 食品局 食品召回", "url": "https://www.sfa.gov.sg/news-publications/newsroom"},
    "CPSC": {"name": "美国 消费品安全委员会 召回 (CPSC)", "url": "https://www.cpsc.gov/Recalls"},
    "AU": {"name": "澳大利亚 农业部 进口食品不合格报告",
           "url": "https://www.agriculture.gov.au/biosecurity-trade/import/goods/food/inspection-testing/failing-food-reports"},
    "CN": {"name": "中国大陆 市场监管总局 抽检抽查不合格", "url": "https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/spcjs/"},
    "SZ": {"name": "深圳市 市场监管局 抽检抽查不合格", "url": "https://amr.sz.gov.cn/xxgk/qt/ztlm/zdlygk/sygk/spzl_zd/"},
    "HK": {"name": "中国香港 食物安全中心 食物警报", "url": "https://www.cfs.gov.hk/sc_chi/whatsnew/whatsnew_fa/whatsnew_fa.html"},
}
INTL = ("JP", "EU", "KR", "SG", "CPSC", "AU")


def apply_reviews(r, tt, firm_zh):
    """Use the latest reviewed translations and verified Chinese firm names.
    tt: {(kind, source): (zh, status)} from term_translations. Static reference tables always win."""
    raw = r.get("raw") or {}
    fei = r.get("fei") or raw.get("FEINumber") or ""
    r["firm_zh"] = firm_zh.get(fei, "") if r.get("src") == "US" else ""
    if r.get("src") in INTL and tt:
        return apply_intl(r, tt)
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


def apply_intl(r, tt):
    """Japan, EU, Korea: product, detail and problem types come from term_translations."""
    k = r["src"].lower()
    machine, hit = False, False
    po = r.get("product_orig") or ""
    if (f"{k}_product", po) in tt:
        zh, st = tt[(f"{k}_product", po)]
        r["product"] = zh; machine |= st == "machine"; hit = True
    do = {"EU": r.get("subj"), "SG": r.get("sgd"), "CPSC": r.get("cpscd"), "AU": r.get("aur")}.get(r["src"], r.get("vio"))
    if do and (f"{k}_detail", do) in tt:
        zh, st = tt[(f"{k}_detail", do)]
        r["detail"] = zh; machine |= st == "machine"; hit = True
    if do and r["src"] != "SG" and (f"{k}_prob", do) in tt:
        r["problems"] = [x for x in tt[(f"{k}_prob", do)][0].split("|") if x] or ["其他"]
    if hit:
        r["machine_translated"] = machine
    return r


def short(r):
    """Short keys keep the files small."""
    out = _short(r)
    if r.get("firm_gone"):
        out["fd"] = 1  # verified firm marked dissolved (注销) in the admin page
    return out


def _short(r):
    return {"id": r["id"], "src": r["src"], "d": r["pub_date"], "grp": r["grp"], "ind": r.get("ind") or "",
            "p": r.get("product") or "", "p0": r.get("product_orig") or "", "prob": r.get("problems") or [],
            "x": r.get("detail") or "", "lim": r.get("legal_limit") or "", "q": r.get("quantity") or "",
            "f": r.get("firm") or "", "imp": r.get("importer") or "", "lab": bool(r.get("lab_tested")),
            "e": r.get("entry_no") or "", "act": r.get("action") or "", "u": r.get("url") or "",
            "mt": bool(r.get("machine_translated")), "fz": r.get("firm_zh") or "",
            "nt": r.get("ntype") or "", "o": r.get("note") or "",
            "im": r.get("im") or [], "ims": r.get("im_src") or ""}


def run(out_dir):
    cols = "id,src,pub_date,grp,ind,product,product_orig,problems,detail,legal_limit,quantity,firm,importer,lab_tested,entry_no,action,url,machine_translated"
    cols += ",ntype,note,fei:raw->>FEINumber,ind0:raw->>IndustryCodeDescription,vio:raw->>violation,subj:raw->summary->>subject,sgdanger:raw->>danger,sgdesc:raw->>description,sgpic:raw->pictures,cpscd:raw->>_detail_src,cpscimg:raw->Images,aur:raw->>reason"
    rows = db.fetch_all(cols)
    tt = {(t["kind"], t["source"]): (t["zh"], t["status"])
          for t in db.fetch_table("term_translations", "kind,source,zh,status", "&order=kind,source")}
    firm_zh = {f["fei"]: f["zh_name"] for f in db.fetch_table("firm_names", "fei,zh_name", "&order=fei")}
    zh_rows = db.fetch_table("firm_zh", "firm_key,zh_name,dissolved", "&order=firm_key")
    firm_zh2 = {f["firm_key"]: f["zh_name"] for f in zh_rows}
    firm_gone = {f["firm_key"] for f in zh_rows if f.get("dissolved")}
    for r in rows:
        raw = r.get("raw") or {}  # local mode returns whole records instead of the JSON-path columns
        for src, k, rk in (("SG", "sgdanger", "danger"), ("SG", "sgdesc", "description"), ("SG", "sgpic", "pictures"),
                           ("CPSC", "cpscd", "_detail_src"), ("CPSC", "cpscimg", "Images"), ("AU", "aur", "reason")):
            if r.get(k) is None and r.get("src") == src:
                r[k] = raw.get(rk)
        if r.get("src") == "SG":
            r["sgd"] = (r.get("sgdanger") or "") + (("\nDescription: " + r["sgdesc"]) if r.get("sgdesc") else "")
    imgs = images.approved()
    rows = [apply_reviews(r, tt, firm_zh) for r in rows]
    # verified Chinese names by merged English name, for every source
    for r in rows:
        if r.get("firm") and r.get("src") not in ("EU", "SG", "SFA"):
            keys = [firms.firm_key(x) for x in r["firm"].split("；")]
            zh = "；".join(dict.fromkeys(firm_zh2[k] for k in keys if firm_zh2.get(k)))
            if zh:
                r["firm_zh"] = zh
            if any(k in firm_gone for k in keys):
                r["firm_gone"] = True
    for r in rows:
        if r.get("src") == "SG":
            r["im"] = ["sg:" + str(i) for i in (r.get("sgpic") or [])][:6]
        elif r.get("src") == "CPSC":
            r["im"] = [x["URL"] for x in (r.get("cpscimg") or []) if (x or {}).get("URL", "").startswith("https://")][:6]
        elif r["id"] in imgs:
            r["im"] = ["img/" + x["path"] for x in imgs[r["id"]]]
            r["im_src"] = images.host(imgs[r["id"]][0]["page"])
    try:
        cn = cn_site.rows()
    except Exception as e:  # the mainland table is optional; never block the export
        print("cn rows skipped:", e)
        cn = []
    rows += cn
    n_img = images.download_approved(os.path.join(out_dir, "img")) if imgs else 0
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
    print(f"mainland sampling rows: {len(cn)}")
    print(f"exported {len(rows)} records in {len(years)} year files, {n_img} approved images")
