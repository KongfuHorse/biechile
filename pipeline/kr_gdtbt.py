"""Older Korea records (before our direct MFDS data starts) from the Guangdong WTO/SPS platform's monthly
reports "中国食品出口韩国违反情况（YYYY年M月）" (sps.gdtbt.org.cn, column TBT-SPS专题研究).

The site refuses plain downloads, so the NAS opens the pages with a real browser ('browse' jobs marked
gdtbt_kr=1) and this module parses the table in each report. Rows on or after the first date of our
direct Korea data are skipped, so nothing is counted twice.

Run: python -m pipeline.kr_gdtbt          (parse + store)
     python -m pipeline.kr_gdtbt --dry    (parse, print, store nothing)
"""
import base64
import html as htmllib
import json
import re
import sys

import requests

from . import cn_site, db

NOTE = "2026 年 5 月以前的韩国记录：广东省 WTO/SPS 信息平台编译的韩国食药处数据"
COLS = [("seq", r"序号"), ("product", r"产品名称|品名"), ("cat", r"产品类别|类别|品类"),
        ("firm", r"制造|出口公司|出口企业|生产企业|企业名称|出口商|生产商"), ("prov", r"所属|地市|省份|产地|地区"),
        ("viol", r"违反内容|违规内容|违反事项|不合格原因|违反原因|违规原因"), ("std", r"检测标准|标准值|限量"), ("result", r"检测结果|检验结果|结果"),
        ("date", r"发布日期|通报日期|日期")]


def _cell(s):
    s = re.sub(r"<br\s*/?>|</p>", " ", s or "")
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def _month(title):
    m = re.search(r"(20\d\d)年(\d{1,2})月", title)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _date(s, ym):
    m = re.search(r"(20\d\d)[/\-.年](\d{1,2})[/\-.月](\d{1,2})", s or "")
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"\s*(\d{1,2})[./\-月](\d{1,2})", s or "")
    if m and ym and 1 <= int(m.group(1)) <= 12:  # "10.05": month.day of the report's year
        y = ym[0] - 1 if int(m.group(1)) > ym[1] + 1 else ym[0]
        return f"{y}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    if ym:
        return f"{ym[0]}-{ym[1]:02d}-15"  # month known, day not given
    return None


def rows_of(page):
    """[{col: text}] from the report's table(s); header row found by its column names."""
    out = []
    for table in re.findall(r"<table.*?</table>", page, re.S | re.I):
        cols = None
        for tr in re.findall(r"<tr.*?</tr>", table, re.S | re.I):
            cells = [_cell(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
            if not cells:
                continue
            if cols is None:
                names = []
                for c in cells:
                    c = re.sub(r"\s", "", c)
                    names.append(next((k for k, rx in COLS if re.search(rx, c)), None))
                if names.count(None) <= len(names) - 3 and "product" in names:
                    cols = names
                continue
            d = {k: v for k, v in zip(cols, cells) if k and v and v != "/"}
            if d.get("product") and (d.get("viol") or d.get("firm")):
                out.append(d)
    return out


def problems(text):
    t = text or ""
    p = cn_site.problem_types(t, "x")
    if p == ["产品标准"]:
        if re.search(r"异物|虫|霉变|腐败|变质|温度|卫生|毛发", t):
            p = ["卫生/生产"]
        elif re.search(r"申报|证书|标签|标示|未经|未获|虚假|伪造|文件", t):
            p = ["标签" if re.search(r"标签|标示", t) else "手续/审批"]
    return p


def group(cat, product):
    t = f"{cat or ''} {product or ''}"
    if re.search(r"器具|容器|包装", t):
        return "食品接触材料"
    if re.search(r"保健|健康功能|功能食品", t):
        return "膳食补充剂"
    return "食品"


def records(url, page, title, first_direct):
    ym = _month(title)
    nid = re.search(r"noteshow-(\d+)", url).group(1)
    out = []
    for i, d in enumerate(rows_of(page), 1):
        date = _date(d.get("date"), ym)
        if not date or (first_direct and date >= first_direct):
            continue
        cat_words = r"^(加工食品|农林产品|水产品|畜产品|健康功能食品|器具及容器包装|器具容器包装|食品添加剂|保健功能食品)$"
        for k in ("product", "cat"):
            if d.get(k):
                d[k] = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", d[k])  # "加工 食品"
        if re.match(cat_words, d.get("product") or "") and not re.match(cat_words, d.get("cat") or ""):
            d["product"], d["cat"] = d.get("cat") or "", d["product"]  # a few tables swap the two columns
        viol = d.get("viol") or ""
        firm = d.get("firm") or ""
        letters = [c for c in firm if c.isalpha() and c.isascii()]
        if letters and sum(c.isupper() for c in letters) / len(letters) > 0.6:
            firm = firm.upper()  # the site prints "ON" inside names as "on" ("LonGNAN")
        detail = viol + (f"（检测结果：{d['result']}）" if d.get("result") else "")
        if d.get("std"):
            detail += f"（标准：{d['std']}）"
        note = [f"出口企业所在省份：{d['prov']}"] if d.get("prov") and d["prov"] not in ("未知", "/", "-") else []
        note.append("来源：广东省WTO/SPS信息平台编译的韩国食药处通报《" + title + "》")
        out.append({
            "id": f"KR-GD-{nid}-{i}", "src": "KR", "pub_date": date, "insp_date": None,
            "grp": group(d.get("cat"), d.get("product")), "ind": d.get("cat") or "", "ntype": None,
            "product": d.get("product") or "", "product_orig": "", "problems": problems(viol),
            "detail": detail or "不合格", "legal_limit": "", "quantity": "", "firm": firm,
            "importer": "", "lab_tested": bool(d.get("result")), "entry_no": "", "action": "退回或销毁",
            "note": "；".join(note), "url": url, "raw": {"row": d, "title": title}, "machine_translated": False,
        })
    return out


def downloads():
    jobs = requests.get(f"{db.URL}/rest/v1/nas_jobs?select=id,result&kind=eq.browse&status=eq.done&args->>gdtbt_kr=eq.1&order=id",
                        headers=db._h(), timeout=120).json()
    for j in jobs:
        files = {f["name"]: f["b64"] for f in requests.get(f"{db.URL}/rest/v1/nas_files?select=name,b64&job_id=eq.{j['id']}",
                                                            headers=db._h(), timeout=180).json()}
        for it in (j.get("result") or {}).get("results", []):
            if it.get("file") in files:
                yield it["url"], it.get("title") or "", base64.b64decode(files[it["file"]]).decode("utf-8", "replace")


def collect():
    first = requests.get(f"{db.URL}/rest/v1/records?select=pub_date&src=eq.KR&id=not.like.KR-GD-*&order=pub_date&limit=1",
                         headers=db._h(), timeout=60).json()
    first_direct = first[0]["pub_date"] if first else None
    recs, seen, empty = [], set(), []
    for url, page, title in ((u, p, t) for u, t, p in downloads()):
        m = re.search(r"<h\d[^>]*>([^<]*韩国[^<]*)</h\d>", page) or re.search(r"<title>([^<]+)</title>", page)
        t = _cell(m.group(1)) if m else title
        if url in seen:
            continue
        seen.add(url)
        got = records(url, page, t, first_direct)
        if not got:
            empty.append((url, t))
        recs += got
    return recs, first_direct, empty


if __name__ == "__main__":
    recs, first, empty = collect()
    from collections import Counter
    print("first direct KR date:", first, "records:", len(recs))
    print(sorted(Counter(r["pub_date"][:4] for r in recs).items()))
    for u, t in empty:
        print("  no rows:", t, u)
    if "--dry" in sys.argv:
        json.dump(recs, open("kr_gdtbt.json", "w"), ensure_ascii=False, indent=1)
    else:
        print("stored", db.upsert(recs))
