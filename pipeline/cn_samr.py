"""Mainland food sampling notices (SAMR): parse the notice pages the NAS downloaded into cn_checks,
then compare the labelled companies with the firms on our overseas list.

Input: rows of nas_jobs (kind 'fetch', done) whose URL is a notice page of the SAMR food sampling column.
Run: python -m pipeline.cn_samr            (parse + store + report)
"""
import base64
import datetime
import io
import json
import re
import sys

import requests

from . import db

NUM = "一二三四五六七八九十百零〇"
ROLE = r"(委托|受委托)?(生产|进口|经销|总经销|代理|总代理|出品|分装|监制|销售|加工|制造|灌装|分销)"
PROV = re.compile(r"^(北京市|天津市|上海市|重庆市|内蒙古自治区|广西壮族自治区|西藏自治区|宁夏回族自治区|新疆维吾尔自治区|新疆生产建设兵团|[一-龥]{2,3}省)")

def cn2int(s):
    d = {c: i for i, c in enumerate("零一二三四五六七八九")}; d["〇"] = 0
    n, cur = 0, 0
    for c in s:
        if c == "百": n += (cur or 1) * 100; cur = 0
        elif c == "十": n += (cur or 1) * 10; cur = 0
        else: cur = d.get(c, 0)
    return n + cur

def header(text):
    h = {}
    m = re.search(r"文号[:：]\s*([^\n]+)", text);  h["no"] = m.group(1).strip() if m else None
    m = re.search(r"发布日期[:：]\s*(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    h["date"] = "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3))) if m else None
    return h

def split_label(label):
    """'A委托B生产的、C进口的X' -> ([(name, role)], product)"""
    firms, rest = [], label
    while True:
        m = re.match(r"(.+?)(?:（[^）]*）)?" + ROLE + r"的[、，]?", rest)
        if not m or len(m.group(1)) > 60: break
        name = m.group(1)
        if "委托" in name and not name.endswith("委托"):
            a, b = name.split("委托", 1)
            firms.append((a.strip("、"), "委托方")); name = b
        name = name.strip("、 ")
        if not re.search(r"(公司|厂|店|社|部|场|坊|行|中心|集团|LLC|LLP|Ltd|Inc|Co\.|S\.A|GmbH|[A-Za-z]{4,})", name) and firms == []:
            break
        firms.append((name, m.group(3)))
        rest = rest[m.end():]
    return firms, rest.strip()

def parse(text, url, title):
    h = header(text)
    body = text
    parts = re.split(r"\n\s*[（(]([%s]{1,5})[)）]" % NUM, body)
    out = []
    for i in range(1, len(parts) - 1, 2):
        no, raw = cn2int(parts[i]), parts[i + 1].strip()
        raw = re.split(r"\n\s*(特此通[报告]|附件|[一二三四五六七八九十]、)", raw)[0].strip()
        raw = re.sub(r"\s*\n\s*", "", raw)
        if "不符合" not in raw and "检出" not in raw and "不合格" not in raw: continue
        first, _, note = raw.partition("。")
        m = re.match(r"(.*?)，(?:其中)?(.*)$", first) if "，其中" not in first else re.match(r"(.*?)，其中(.*)$", first)
        head, problem = (m.group(1), m.group(2)) if m else (first, "")
        seller = platform = origin = None; label = head
        ms = re.match(r"(.*?)销售的[、，]?(?:标称)?(.*)$", head)
        if ms: seller, label = ms.group(1), ms.group(2)
        else:
            ms = re.match(r"(.*?)(自行消毒的|自制的|加工的|制作的|使用的|经营的)(.*)$", head)
            if ms: seller, label = ms.group(1), ms.group(3)
        if seller:
            mp = re.search(r"在(.+?)(?:（[^）]*）)?$", seller)
            if mp and re.search(r"(淘宝|天猫|京东|拼多多|抖音|快手|微信|百度|小红书|苏宁|网|APP|商城|平台)", mp.group(1)):
                platform = mp.group(1); seller = seller[:mp.start()]
            seller = re.sub(r"（(店铺名|经营者|网店|店名)[^）]*）", "", seller).strip("、， ")
        label = re.sub(r"^标称", "", label)
        mo = re.search(r"（标称原产(?:国|地)[:：]\s*([^）]+)）", label)
        if mo: origin = mo.group(1); label = label.replace(mo.group(0), "")
        firms, product = split_label(label)
        maker = next((n for n, r in reversed(firms) if r in ("生产", "加工", "制造", "灌装", "分装")), firms[0][0] if firms else None)
        disputed = bool(re.search(r"异议|假冒|不是.{0,40}(生产|进口|经销)|冒用|仿冒", note))
        out.append({"notice_url": url, "notice_title": title, "notice_no": h["no"], "notice_date": h["date"], "item_no": no,
                    "maker": maker, "maker_role": "；".join("%s:%s" % (r, n) for n, r in firms) or None,
                    "product": product or None, "problem": problem.rstrip("。") or None, "seller": seller or None,
                    "platform": platform, "origin": origin, "disputed": disputed, "dispute_note": note.strip() or None, "raw": raw})
    return out


SUF = re.compile(r"(股份有限公司|有限责任公司|有限公司|集团|公司|厂)$")


def key(n):
    """Company name without bracketed parts, place prefix and company suffix, for matching."""
    n = re.sub(r"[（(].*?[)）]", "", n or "")
    n = re.sub(r"\s", "", n)
    while PROV.match(n):
        n = PROV.sub("", n, 1)
    if len(n) > 8:
        n = re.sub(r"^[一-龥]{2,4}?(市|州|盟|地区)", "", n)
    for _ in range(2):
        n = SUF.sub("", n)
    return n


def _html_text(html):
    """Visible text of a notice page, with paragraph breaks kept."""
    m = re.search(r"<!--\s*正文开始?\s*-->(.*?)<!--\s*正文结束\s*-->", html, re.S)
    body = m.group(1) if m else html
    body = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", body)
    body = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>|</li>|</tr>", "\n", body)
    body = re.sub(r"<[^>]+>", "", body)
    body = re.sub(r"&nbsp;|&#160;", " ", body).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"[ \t\u3000]*\n[ \t\u3000\n]*", "\n\n", body)


def notices(since=None):
    """Yield (url, title, text, [(attachment name, bytes)]) for every notice page the NAS has downloaded
    (only jobs created on or after since, if given). The newest download of a page wins."""
    jobs = db.fetch_table("nas_jobs", "id", "&kind=eq.pages&status=eq.done&order=id.desc" + (f"&finished_at=gte.{since}" if since else ""))
    done = set()
    for row in jobs:
        r = requests.get(f"{db.URL}/rest/v1/nas_jobs?select=result&id=eq.{row['id']}", headers=db._h(), timeout=120)
        r.raise_for_status()
        res = (r.json()[0]["result"] or {}).get("results", [])
        files = {}
        if any(d.get("file") for it in res for d in it.get("docs", [])):
            f = requests.get(f"{db.URL}/rest/v1/nas_files?select=name,b64&job_id=eq.{row['id']}", headers=db._h(), timeout=120)
            f.raise_for_status()
            files = {x["name"]: x["b64"] for x in f.json()}
        for it in res:
            u = it.get("url", "")
            if u in done or "/spcjs/art/" not in u or not it.get("html"):
                continue
            done.add(u)
            html = it["html"]
            m = re.search(r"<title>(.*?)</title>", html, re.S)
            title = re.sub(r"\s+", "", m.group(1)) if m else ""
            title = re.sub(r"[-_|].*$", "", title) or title
            docs = [(d["name"], base64.b64decode(files[d["file"]])) for d in it.get("docs", [])
                    if d.get("file") in files and d.get("ext") in ("xlsx", "xls")]
            yield u, title, _html_text(html), docs


HEAD = {
    "序号": "seq", "标称生产企业名称": "maker", "标称生产企业地址": "maker_addr", "被抽样单位名称": "seller",
    "被抽样单位地址": "seller_addr", "样品名称": "product", "食品名称": "product", "规格型号": "spec", "商标": "brand",
    "生产日期": "prod_date", "生产日期/批号": "prod_date", "生产日期（批号）": "prod_date", "不合格项目": "problem",
    "不合格项目║检验结果║标准值": "problem", "检验结果": "test_value", "检验值": "test_value", "标准值": "standard_value",
    "检验机构": "lab", "食品细类": "category", "分类": "category", "抽样编号": "sample_no", "备注": "note",
}


def _cell(v):
    if v is None:
        return None
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.strftime("%Y-%m-%d")
    v = re.sub(r"\s+", " ", str(v)).strip()
    return None if v in ("", "/", "-", "—") else v


def read_sheet(data):
    """Rows of a failed-sample table as dicts (keys from HEAD). Header row found by its 序号 cell."""
    rows = []
    try:
        if data[:4] == b"PK\x03\x04":
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
            sheets = [list(ws.iter_rows(values_only=True)) for ws in wb.worksheets]
        else:
            import xlrd
            wb = xlrd.open_workbook(file_contents=data)
            sheets = [[sh.row_values(i) for i in range(sh.nrows)] for sh in wb.sheets()]
    except Exception as e:
        print("  cannot read sheet:", e)
        return rows
    for sh in sheets:
        cols = None
        for raw in sh:
            vals = [_cell(v) for v in raw]
            if cols is None:
                names = [re.sub(r"\s", "", v or "") for v in vals]
                if "序号" in names and any("名称" in n for n in names):
                    cols = [HEAD.get(n) for n in names]
                    # a second 备注 column holds the sale channel
                    seen = set()
                    for i, c in enumerate(cols):
                        if c == "note" and "note" in seen:
                            cols[i] = "channel"
                        if c:
                            seen.add(c)
                continue
            if not any(vals):
                continue
            d = {c: v for c, v in zip(cols, vals) if c and v}
            if d.get("product") and (d.get("maker") or d.get("seller")):
                rows.append(d)
    return rows


def from_sheets(url, title, no, date, text_rows, docs):
    out = []
    for fi, (name, data) in enumerate(docs, 1):
        for i, d in enumerate(read_sheet(data), 1):
            note = " ".join(x for x in (d.get("note"), d.get("channel")) if x)
            maker = d.get("maker")
            # link back to the paragraph in the notice text, for the other labelled firms and the dispute result
            t = next((r for r in text_rows if d["product"] and r["product"] and (d["product"] in r["product"] or r["product"] in d["product"])
                      and (not maker or (r["maker_role"] or "").find(re.sub(r"^.*?：", "", maker.split("；")[0])[:4]) >= 0
                           or (r["seller"] or "").find((d.get("seller") or "")[:4]) >= 0)), None)
            if maker and "：" in maker:  # "经销商：A；生产商：/；原产国：美国"
                parts = dict(p.split("：", 1) for p in maker.split("；") if "：" in p)
                maker = next((v for k, v in parts.items() if "生产" in k and v not in ("/", "")), None) or \
                        next((v for v in parts.values() if v not in ("/", "")), None)
            dispute = (t or {}).get("dispute_note") or ""
            disputed = bool(re.search(r"异议|假冒|不是.{0,40}(生产|进口|经销)|冒用|仿冒", note + dispute))
            out.append({"notice_url": url, "notice_title": title, "notice_no": no, "notice_date": date,
                        "item_no": fi * 1000 + i, "source": "xlsx", "attachment": name,
                        "maker": maker, "maker_addr": d.get("maker_addr"), "maker_role": (t or {}).get("maker_role") or (f"生产:{maker}" if maker else None),
                        "product": d.get("product"), "problem": d.get("problem"), "test_value": d.get("test_value"),
                        "standard_value": d.get("standard_value"), "seller": d.get("seller"), "seller_addr": d.get("seller_addr"),
                        "platform": (t or {}).get("platform"), "origin": (t or {}).get("origin"), "spec": d.get("spec"),
                        "brand": d.get("brand"), "prod_date": d.get("prod_date"), "lab": d.get("lab"), "category": d.get("category"),
                        "sample_no": d.get("sample_no"), "disputed": disputed,
                        # 2019 notices also attached tables of samples that passed
                        "passed": not d.get("problem") and "不合格" not in name,
                        "dispute_note": (dispute or note or None), "raw": json.dumps(d, ensure_ascii=False)})
    return out


def store(rows):
    for i in range(0, len(rows), 300):
        r = requests.post(f"{db.URL}/rest/v1/cn_checks?on_conflict=notice_url,item_no",
                          headers=db._h({"Prefer": "resolution=merge-duplicates,return=minimal"}),
                          data=json.dumps(rows[i:i + 300]).encode(), timeout=120)
        if r.status_code >= 400:
            raise RuntimeError(f"cn_checks: {r.status_code} {r.text[:300]}")


def our_firms():
    out = [("verified", f["firm_key"], f["zh_name"]) for f in db.fetch_table("firm_zh", "firm_key,zh_name")]
    for a in db.fetch_table("firm_ai", "firm_key,candidates"):
        out += [("ai-" + (c.get("basis") or ""), a["firm_key"], c.get("name")) for c in a["candidates"] or []]
    tw = {r["firm"] for r in db.fetch_table("records", "firm", "&src=eq.TW&firm=not.is.null")}
    out += [("tw", f, f) for f in tw if re.search(r"[一-龥]", f)]
    return [(k, fk, n) for k, fk, n in out if n and re.search(r"[一-龥]", n)]


def collect(since=None):
    """Parsed rows (deduplicated) and a short report of the notices downloaded since the given date."""
    rows, n_notices, empty = [], 0, []
    n_sheet = 0
    for url, title, text, docs in notices(since):
        n_notices += 1
        got = parse(text, url, title)
        h = header(text)
        sheet = from_sheets(url, title, h["no"], h["date"], got, docs) if docs else []
        if sheet:
            n_sheet += 1
            rows += sheet
        else:
            for r in got:
                r["source"] = "text"
                r["passed"] = False
            rows += got
        if not got and not sheet:
            empty.append(f"{title} {url}")
    seen, uniq = set(), []
    for r in rows:
        k = (r["notice_url"], r["item_no"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    keys = sorted({k for r in uniq for k in r})
    uniq = [{k: r.get(k) for k in keys} for r in uniq]
    for r in uniq:
        r["disputed"] = bool(r["disputed"])
    return uniq, n_notices, n_sheet, empty


def main():
    uniq, n_notices, n_sheet, empty = collect()
    store(uniq)
    years = {}
    for r in uniq:
        y = (r["notice_date"] or "?")[:4]
        years[y] = years.get(y, 0) + 1
    print(f"notices {n_notices}, items {len(uniq)}, with maker {sum(1 for r in uniq if r['maker'])}, "
          f"disputed {sum(r['disputed'] for r in uniq)}, by year {dict(sorted(years.items()))}")
    print(f"notices read from Excel tables: {n_sheet}; from text only: {n_notices - n_sheet}")
    print(f"notices with no parsed items: {len(empty)}")
    for e in empty[:40]:
        print("  EMPTY", e)

    names = {}
    for r in uniq:
        for part in (r["maker_role"] or "").split("；"):
            if ":" in part:
                role, nm = part.split(":", 1)
                names.setdefault(nm, []).append((role, r))
    idx = {}
    for nm in names:
        idx.setdefault(key(nm), []).append(nm)
    print(f"distinct labelled companies: {len(names)}; passed samples: {sum(r['passed'] for r in uniq)}")
    firms = our_firms()
    hit_firms, lines = set(), []
    for kind, fk, n in firms:
        k = key(n)
        if len(k) < 4:
            continue
        for nm in idx.get(k, []):
            a, b = re.findall(r"[（(](.*?)[)）]", n), re.findall(r"[（(](.*?)[)）]", nm)
            if a and b and a[0] != b[0]:  # 中粮米业（大连） is not 中粮米业（五常）
                continue
            hit_firms.add(fk)
            for role, r in names[nm]:
                lines.append(f"MATCH {'合格' if r['passed'] else '不合格'} [{kind}] {fk[:50]} | {n} => {nm} | {role} | {r['product']} | {(r['problem'] or '')[:40]} | "
                             f"{r.get('maker_addr') or ''} | "
                             f"{r['notice_date']}{' | 有异议/假冒核实' if r['disputed'] else ''} | {r['notice_url']}")
    for line in sorted(set(lines)):
        print(line)
    print(f"matched {len(hit_firms)} of {len({fk for _, fk, _ in firms})} firms on our list that have a Chinese name or candidate")


if __name__ == "__main__":
    sys.exit(main())
