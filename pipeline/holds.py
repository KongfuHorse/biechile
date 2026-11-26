"""Import hold lists: firms whose goods are held at the border until checked.

US: FDA import alerts, "red list" (Detention Without Physical Examination). Firms are added after
violations and taken off only after FDA grants a petition (often 5 clean shipments). The alert pages
show only the current list, so a firm that disappears is recorded as removed on the day we notice.

AU: Department of Agriculture holding orders. Revocations are published monthly with a date. The
site refuses automated downloads, so ref/au_holding.tsv is refreshed by hand about once a month.

Table holds (one row per list entry, kept after removal with removed_on set):
    src, ref, firm_key, firm, address, groups, products, reason, listed_on, first_seen, last_seen,
    removed_on, url

    python -m pipeline.holds --dry   (fetch and parse, write holds.json, store nothing)
"""
import datetime as dt
import html as H
import json
import os
import re
import sys
import time

import requests

from . import db
from .firms import firm_key
from .normalize import fda_group

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IA = "https://www.accessdata.fda.gov/cms_ia/"
UA = {"User-Agent": "Mozilla/5.0 (biechile.com data collector)"}
AU_DOCS = "https://www.agriculture.gov.au/sites/default/files/documents/"
LEGACY = "2009-09-30"  # FDA moved its import alerts to the current system on this date; earlier entries carry it


def _ref(name):
    return json.load(open(os.path.join(ROOT, "ref", name), encoding="utf-8"))


def _get(url):
    for i in range(4):
        try:
            r = requests.get(url, headers=UA, timeout=90)
            r.raise_for_status()
            r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else "utf-8"
            return r.text
        except requests.RequestException:
            if i == 3:
                raise
            time.sleep(5 * (i + 1))


def _txt(s):
    return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")).strip()


def _iso(mdY):
    m, d, y = mdY.split("/")
    return f"{y}-{int(m):02d}-{int(d):02d}"


def fda_alert(page, page_id):
    """China entries on the red list of one import alert page."""
    s = re.sub(r"\s+", " ", page)
    num = re.search(r"Import Alert (\d+-\d+)", s)
    num = num.group(1) if num else page_id
    heads = [(m.start(), _txt(m.group(1))) for m in re.finditer(r"<h\d[^>]*>(.*?)</h\d>", s)]
    red = None
    for k, (pos, t) in enumerate(heads):
        if "Red List" in t:
            end = next((p2 for p2, t2 in heads[k + 1:] if re.search(r"Green List|Yellow List|exclusion from", t2)), len(s))
            red = s[pos:end]
            break
    if red is None:
        return num, []
    m = re.search(r"<h4>\s*CHINA\s*</h4>(.*?)(?=<h4>|$)", red)
    if not m:
        return num, []
    out = []
    for p in re.split(r'<div class="div-info">', m.group(1))[1:]:
        name = re.search(r'<div class="div-name floatleft">(.*?)</div>', p)
        addr = re.search(r'<div class="clear">(.*?)</div>', p)
        fdate = re.search(r"Date Published\s*:\s*(\d\d/\d\d/\d{4})", p)
        prods = []
        for pm in re.finditer(r"<em>(.*?)</em>(.*?)<br>.*?Date Published:\s*(\d\d/\d\d/\d{4})(.*?)(?=<div> <div class=\"floatleft\"><em>|$)", p):
            desc = re.search(r"<div>Desc:(.*?)</div>", pm.group(4))
            prods.append({"code": _txt(pm.group(1)).replace(" ", ""), "product": _txt(pm.group(2)),
                          "date": _iso(pm.group(3)), "desc": _txt(desc.group(1)) if desc else ""})
        firm = _txt(name.group(1)) if name else ""
        if not firm:
            continue
        dates = [x["date"] for x in prods] or ([_iso(fdate.group(1))] if fdate else [])
        out.append({"src": "US", "ref": num, "firm": firm, "firm_key": firm_key(firm),
                    "address": _txt(addr.group(1)) if addr else "", "products": prods,
                    "listed_on": min(dates) if dates else None, "url": f"{IA}importalert_{page_id}.html"})
    return num, out


def fda_fetch():
    index = _get(IA + "country_CN.html")
    ids = sorted(set(re.findall(r"importalert_(\d+)\.html", index)), key=int)
    entries, ok = [], 0
    for i in ids:
        try:
            _, rows = fda_alert(_get(f"{IA}importalert_{i}.html"), i)
            entries += rows
            ok += 1
        except Exception as e:
            print("import alert page failed:", i, e)
        time.sleep(0.5)
    return _merge(entries), ok, len(ids)


def _merge(entries):
    """One entry per alert and firm (a firm can appear twice with two addresses)."""
    out = {}
    for e in entries:
        k = (e["ref"], e["firm_key"])
        if k in out:
            out[k]["products"] += e["products"]
            out[k]["listed_on"] = min(x for x in (out[k]["listed_on"], e["listed_on"]) if x) if (out[k]["listed_on"] or e["listed_on"]) else None
        else:
            out[k] = e
    return list(out.values())


def fda_describe(entries):
    """Chinese product names, groups and reasons for FDA entries."""
    pz = {k.upper(): v for k, v in _ref("fda_product_zh.json").items()}
    pz.update({k.upper(): v for k, v in _ref("fda_ia_product_zh.json").items()})
    az = _ref("fda_ia_alert_zh.json")
    for e in entries:
        groups, names = [], []
        for p in e["products"]:
            try:
                g = fda_group(p["code"])
            except ValueError:
                g = "其他"
            if g == "食品" and p["code"][:3] == "52A":
                g = "食品接触材料"
            groups.append(g)
            names.append(pz.get(p["product"].upper()) or g)
        e["groups"] = list(dict.fromkeys(groups)) or ["其他"]
        e["products_zh"] = list(dict.fromkeys(names))
        e["reason"] = az.get(e["ref"], "")
    return entries


def au_rows():
    out = []
    for ln in open(os.path.join(ROOT, "ref", "au_holding.tsv"), encoding="utf-8"):
        if ln.startswith("#") or not ln.strip():
            continue
        no, d, prod, zh, producer, revoked, f = (ln.rstrip("\n").split("\t") + [""] * 7)[:7]
        out.append({"src": "AU", "ref": no, "firm": producer, "firm_key": firm_key(producer), "address": "",
                    "products": [{"product": prod, "date": d}], "products_zh": [zh or prod], "groups": ["食品"],
                    "reason": "检验不合格", "listed_on": d if len(d) == 10 else d + "-01", "listed_month_only": len(d) == 7,
                    "revoked": revoked or None, "url": AU_DOCS + f})
    return out


# ---------- Japan: MHLW inspection orders that name Chinese manufacturers ----------

JP_INDEX = "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/shokuhin/yunyu_kanshi/kanshi/index.html"
JP_TABLES = {  # tables of the yearly inspection-order notice that list named manufacturers
    "cyclamate": (r"中国産食品（サイクラミン酸）検査命令対象製造者", "检出甜蜜素"),
    "aflatoxin": (r"食品（(?:総)?アフラトキシン）検査命令対象製造者", "检出黄曲霉毒素"),
}
JP_WORDS = [("ピスタチオナッツ", "开心果"), ("赤とうがらし", "红辣椒"), ("ごまの種子", "芝麻"), ("落花生", "花生"),
            ("アーモンド", "杏仁"), ("ラカンカ", "罗汉果"), ("くるみ", "核桃"), ("とうもろこし", "玉米"),
            ("ターメリック", "姜黄"), ("ひよこ豆", "鹰嘴豆"), ("うるち米", "大米"), ("ナツメグ", "肉豆蔻"),
            ("くり", "栗子"), ("花椒", "花椒"), ("大豆", "大豆"), ("乾燥", "干"), ("又は", "或"), ("（甘味種を除く。）", "（甜玉米除外）")]


def _jp_item(item):
    """'落花生を含む食品' -> '含花生的食品'"""
    m = re.fullmatch(r"(.+)を含む食品", item)
    if not m:
        return item
    x = m.group(1)
    for ja, zh in JP_WORDS:
        x = x.replace(ja, zh)
    return "含" + x + "的食品"


def _pdf_rows(data):
    import io
    import pdfplumber
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        tables = [r for pg in pdf.pages for t in pg.extract_tables() for r in t]
        text = "\n".join(pg.extract_text() or "" for pg in pdf.pages)
    return tables, text


def jp_fetch():
    """Current entries, and whether every table was read."""
    idx = _get(JP_INDEX)
    year = next(h for h, t in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', idx, re.S) if "検査命令実施通知" in t)
    year = year if year.startswith("http") else "https://www.mhlw.go.jp" + year
    ypage = _get(year)
    base = next(h for h, t in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', ypage, re.S) if "第26条第3項に基づく検査命令の実施について" in _txt(t))
    page = re.sub(r"\s+", " ", _get(base))
    dates = _ref("jp_hold_dates.json")
    out, found = [], 0
    for key, (pat, reason) in JP_TABLES.items():
        m = re.search(pat + r'[^<]*<a[^>]+href="([^"]+\.pdf)"', page) or re.search(pat + r'.{0,40}?\(\s*<a[^>]+href="([^"]+\.pdf)"', page)
        if not m:
            print("Japan table not found:", key)
            continue
        url = "https://www.mhlw.go.jp" + m.group(1) if m.group(1).startswith("/") else m.group(1)
        r = requests.get(url, headers=UA, timeout=90)
        r.raise_for_status()
        tables, text = _pdf_rows(r.content)
        rows = []
        if key == "cyclamate":
            for ln in text.split("\n"):
                ln = re.sub(r"^[A-Z]\s+", "", ln.strip())
                if re.search(r"(CO\.|LTD|LIMITED|COMPANY|CORP)", ln, re.I):
                    rows.append((ln, "所有食品"))
        else:
            country = None
            item = None
            for row in tables:
                row = [(c or "").replace("\n", "") for c in row] + ["", "", ""]
                if row[0] == "対象国":
                    continue
                country = row[0] or country
                item = row[1] or item
                if country == "中国" and row[2]:
                    rows.append((row[2].strip(), _jp_item(item or "")))
        if rows:
            found += 1
        for firm, prod in rows:
            k = firm_key(firm)
            out.append({"src": "JP", "ref": key, "firm": firm, "firm_key": k, "address": "",
                        "products": [{"product": prod}], "products_zh": [prod], "groups": ["食品"],
                        "reason": reason, "listed_on": dates.get(k), "url": url})
    return _merge(out), found == len(JP_TABLES)


# ---------- Korea: MFDS overseas manufacturers whose imports are suspended ----------

KR_LIST = ("https://impfood.mfds.go.kr/CFCCC01F08/getList2?page={page}&limit=100&active2=active&srchBsshCode=&srchEstCd="
           "&srchBsshTy=ovsmnfst&srchBsshSttus=END&srchNtnCd=CN&srchBsshNm=&srchBsshAddr=&srchFoodSeCd=")
KR_PAGE = "https://impfood.mfds.go.kr/CFCCC01F08"


def kr_fetch():
    """Current list, and whether it was read to the end (the last page has fewer than 100 rows)."""
    out, page, complete = [], 1, False
    while page <= 20:
        s = re.sub(r"<!--.*?-->", "", _get(KR_LIST.format(page=page)), flags=re.S)
        s = re.sub(r'<strong class="td-title"[^>]*>.*?</strong>', "", s, flags=re.S)
        tb = s[s.find("<tbody"):s.find("</tbody>")]
        rows = [[_txt(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)] for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S)]
        rows = [r for r in rows if len(r) >= 8 and re.match(r"[A-Z]{2}\d+", r[1])]
        for r in rows:
            # 번호 업소코드 업소분류 국가 업소명 구분 기준일 중단시작일 해제일 비고
            out.append({"src": "KR", "ref": r[1], "firm": r[4], "firm_key": firm_key(r[4]), "address": "",
                        "products": [], "products_zh": [], "groups": ["食品"], "reason": "暂停进口",
                        "listed_on": r[7] if re.fullmatch(r"\d{4}-\d\d-\d\d", r[7]) else None, "url": KR_PAGE})
        if len(rows) < 100:
            complete = True
            break
        page += 1
    return out, complete


# ---------- database ----------

def _rest(path, method="GET", **kw):
    r = requests.request(method, f"{db.URL}/rest/v1/{path}", headers=db._h(kw.pop("headers", {})), timeout=120, **kw)
    r.raise_for_status()
    return r.json() if r.text and method == "GET" else None


def _row(e, today):
    return {"src": e["src"], "ref": e["ref"], "firm_key": e["firm_key"], "firm": e["firm"], "address": e.get("address", ""),
            "groups": e["groups"], "products": e["products"], "products_zh": e["products_zh"], "reason": e["reason"],
            "listed_on": e["listed_on"], "url": e["url"], "last_seen": today}


def sync(src, entries, removals_ok=True):
    """Upsert the current list. Active rows missing from it get removed_on (FDA) unless removals_ok is False."""
    today = dt.date.today().isoformat()
    active = {(r["ref"], r["firm_key"]): r for r in
              db.fetch_table("holds", "ref,firm_key,first_seen", f"&src=eq.{src}&removed_on=is.null&order=ref,firm_key")}
    seen = {}
    for e in entries:
        k = (e["ref"], e["firm_key"])
        row = _row(e, today)
        if e.get("revoked"):
            row["removed_on"] = e["revoked"]
        else:
            row["removed_on"] = None
        row["first_seen"] = (active.get(k) or {}).get("first_seen") or today
        seen[k] = row
    rows = list(seen.values())
    for i in range(0, len(rows), 500):
        _rest("holds?on_conflict=src,ref,firm_key", "POST", json=rows[i:i + 500],
              headers={"Prefer": "resolution=merge-duplicates,return=minimal"})
    gone = [k for k in active if k not in seen]
    if removals_ok:
        for ref, fk in gone:
            _rest(f"holds?src=eq.{src}&ref=eq.{requests.utils.quote(ref)}&firm_key=eq.{requests.utils.quote(fk)}", "PATCH",
                  json={"removed_on": today}, headers={"Prefer": "return=minimal"})
    print(f"holds {src}: {len(rows)} on list, {len(gone)} no longer listed" + ("" if removals_ok else " (not marked: fetch incomplete)"))
    return len(rows), len(gone)


def run():
    entries, ok, n = fda_fetch()
    fda_describe(entries)
    before = db.fetch_table("holds", "ref", "&src=eq.US&removed_on=is.null&order=ref,firm_key")
    # a page that failed to load must not look like a mass removal
    complete = n > 0 and ok == n and len(entries) >= 0.8 * len(before)
    sync("US", entries, removals_ok=complete)
    sync("AU", au_rows(), removals_ok=False)  # AU removals come from the revocation dates in the file
    for src, fetch in (("JP", jp_fetch), ("KR", kr_fetch)):
        try:
            rows, ok = fetch()
            sync(src, rows, removals_ok=ok and len(rows) > 0)
        except Exception as e:
            print(f"holds {src} failed:", e)


if __name__ == "__main__":
    if "--dry-jpkr" in sys.argv:
        jp, jok = jp_fetch()
        kr, kok = kr_fetch()
        open("kr_raw.html", "w").write(_get(KR_LIST.format(page=1)))
        json.dump({"jp": jp, "kr": kr, "jp_ok": jok, "kr_ok": kok}, open("holds_jpkr.json", "w"), ensure_ascii=False)
        print("JP", len(jp), jok, "KR", len(kr), kok)
    elif "--dry" in sys.argv:
        e, ok, n = fda_fetch()
        fda_describe(e)
        json.dump({"fda": e, "au": au_rows(), "pages_ok": ok, "pages": n}, open("holds.json", "w"), ensure_ascii=False)
        print(len(e), "FDA entries from", ok, "of", n, "pages")
    else:
        run()


def site_rows(entries, zh=None):
    """Active entries grouped per country and firm, with short keys for site/data/holds.json."""
    zh = zh or {}
    groups = {}
    for e in entries:
        if e.get("removed_on") or e.get("revoked"):
            continue
        k = (e["src"], e["firm_key"])
        g = groups.setdefault(k, {"s": e["src"], "f": e["firm"], "fz": zh.get(e["firm_key"], ""), "g": [], "p": [],
                                  "r": [], "d": None, "dm": 0})
        g["g"] += [x for x in e["groups"] if x not in g["g"]]
        g["p"] += [x for x in e["products_zh"] if x not in g["p"]]
        # link kept short: the alert page id (US) or the instrument file name (AU)
        link = {"US": lambda u: u.rsplit("_", 1)[-1].replace(".html", ""), "KR": lambda u: ""}.get(e["src"], lambda u: u.rsplit("/", 1)[-1])
        g["r"].append([e["reason"], e["ref"], link(e["url"])])
        d = e.get("listed_on")
        if d and (g["d"] is None or d < g["d"]):
            g["d"], g["dm"] = d, 1 if e.get("listed_month_only") else 0
    out = []
    for g in groups.values():
        named = [x for x in g["p"] if x not in g["g"]]  # a bare group name only stands in for an untranslated product
        g["p"] = named or g["p"]
        if len(g["p"]) > 6:
            g["pn"], g["p"] = len(g["p"]), g["p"][:6]
        if g["d"] == LEGACY:
            g["d"], g["dm"] = "", 2  # listed before FDA's 2009 system change; the real date is not shown
        if not g["dm"]:
            del g["dm"]
        out.append(g)
    out.sort(key=lambda g: (g["d"] or "0000"), reverse=True)
    return out
