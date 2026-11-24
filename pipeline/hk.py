"""Hong Kong Centre for Food Safety (CFS): food alerts and unsatisfactory sample results.

Both lists are plain HTML tables in Simplified Chinese, so no translation or AI is needed.
Only products whose stated place of origin is mainland China are kept. Unsatisfactory samples
without a stated origin (most fresh produce taken from shops or restaurants) are left out,
because we cannot tell where they came from.
"""
import datetime
import html as htmllib
import json
import re
import time

import requests

from . import cn_site, sfa

BASE = "https://www.cfs.gov.hk"
FA_YEAR = BASE + "/sc_chi/whatsnew/whatsnew_fa/whatsnew_fa_{y}.html"
US_LIST = BASE + "/filemanager/pressrelease/sc_chi/list_UnsatisfactorySampleResult_7954_2.js"
US_MONTH = BASE + "/sc_chi/unsat_samples/{m:02d}-{y}.html"
VIA_DB = [0]
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0 Safari/537.36"}


def get(url):
    try:
        r = requests.get(url, headers=UA, timeout=60)
        if r.status_code == 200 and r.content:
            r.encoding = "utf-8"
            return r.text.lstrip("\ufeff")
        if r.status_code == 404:
            return ""
    except requests.RequestException:
        pass
    VIA_DB[0] += 1
    return sfa._via_db(url).lstrip("\ufeff")  # Hong Kong sometimes refuses cloud servers; go through the database


def _text(s):
    s = (s or "").replace("\r", "")
    s = re.sub(r"<(br|/p|/li|/tr|/h\d)\b[^>]*>", "\n", s or "")
    s = htmllib.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    lines = [re.sub(r"[ \t　]+", " ", x).strip(" -") for x in s.split("\n")]
    return "\n".join(x for x in lines if x)


def table(page):
    """{header: text} of the first data table on a CFS page."""
    out = {}
    for th, td in re.findall(r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", page, re.S):
        out[_text(th).rstrip(":：")] = _text(td)
    return out


def title(page):
    m = re.search(r"<h2[^>]*>(.*?)</h2>", page, re.S)
    return _text(m.group(1)) if m else ""


def _field(lines, *names):
    for ln in lines:
        m = re.match(r"(%s)\s*[:：︰]\s*(.+)" % "|".join(names), ln)
        if m:
            return m.group(2).strip()
    return ""


def mainland(origin):
    o = origin or ""
    return "中国" in o and not re.search(r"香港|台湾|澳门|台灣|澳門", o) or "内地" in o


def _types(head, text, limit):
    t = cn_site.problem_types(head + " " + text, limit)
    if "标签" in head and t == ["产品标准"]:
        t = ["标签"]
    return t


# ---------- food alerts ----------

def alert_urls(year):
    page = get(FA_YEAR.format(y=year))
    return sorted(set(BASE + u for u in re.findall(r'href="(/sc_chi/whatsnew/whatsnew_fa/\d{4}_\d+\.html)"', page)))


def _products(info):
    """Split the 产品名称及资料 cell into one dict per product."""
    prods, cur = [], []
    for ln in info.split("\n"):
        if re.match(r"(产品名称|产品\s*[一二三四五六七八九十\d]+)", ln) and any(x.startswith("产品名称") for x in cur):
            prods.append(cur)
            cur = []
        cur.append(ln)
    if cur:
        prods.append(cur)
    return prods


def parse_alert(url, page):
    t = table(page)
    if not t:
        return []
    d = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", t.get("发出日期", ""))
    date = f"{d.group(3)}-{int(d.group(2)):02d}-{int(d.group(1)):02d}" if d else None
    info = t.get("产品名称及资料", "")
    reason = t.get("发出警报原因", "")
    action = t.get("食物安全中心采取的行动", "")
    head = title(page)
    out = []
    plist = _products(info)
    common_origin = _field(info.split("\n"), "来源地", "原产地", "产地")
    for i, lines in enumerate(plist):
        origin = _field(lines, "来源地", "原产地", "产地") or (common_origin if len(plist) == 1 else "")
        if not mainland(origin):
            continue
        name = _field(lines, "产品名称", "名称") or t.get("食品", "")
        name = re.sub(r"^(产品\s*[一二三四五六七八九十\d]+\s*[:：]?\s*)", "", name)
        brand = _field(lines, "品牌", "牌子", "牌子名称")
        maker = _field(lines, "制造商", "生产商")
        trader = _field(lines, "进口商", "分销商", "代理商", "经销商", "总经销商", "包装商", "零售商")
        rest = [ln for ln in lines if ln.strip() and not re.match(r"(产品名称|名称|品牌|牌子|来源地|原产地|产地|制造商|生产商|进口商|分销商|代理商|经销商|总经销商|包装商|零售商)\s*[:：︰]", ln)]
        note = []
        if brand:
            note.append("品牌：" + brand)
        if trader:
            note.append("香港进口商/分销商：" + trader)
        note += rest[:4]
        note.append("来源地：" + origin)
        if action:
            note.append("食安中心行动：" + action.replace("\n", "；"))
        detail = reason.replace("\n", "；")
        slug = url.rsplit("/", 1)[-1].split(".")[0]
        out.append({
            "id": f"HK-FA-{slug}-{i}", "src": "HK", "pub_date": date, "insp_date": None, "grp": "食品",
            "ind": t.get("食品", ""), "ntype": "食物警报", "product": name, "product_orig": "",
            "problems": _types(head, detail, "x"), "detail": head + "。" + detail,
            "legal_limit": "", "quantity": "", "firm": maker, "importer": trader,
            "lab_tested": bool(re.search(r"检测|检出|验出|含量", detail)), "entry_no": "",
            "action": "停售、回收", "note": "；".join(note)[:800], "url": url,
            "raw": {"table": t, "title": head}, "machine_translated": False,
        })
    return out


# ---------- unsatisfactory samples ----------

def months():
    """[(year, month)] that have unsatisfactory-sample pages."""
    m = json.loads(get(US_LIST) or "{}")
    out = []
    for y, bits in m.items():
        for mo in range(1, 13):
            if int(bits) & (1 << (mo - 1)):
                out.append((int(y), mo))
    return sorted(out)


def sample_urls(year, month):
    page = get(US_MONTH.format(y=year, m=month))
    return sorted(set(BASE + u for u in re.findall(r'href="(/sc_chi/unsat_samples/\d{8}_\d+\.html)"', page)))


def parse_sample(url, page):
    t = table(page)
    origin = t.get("原产地") or t.get("来源地") or t.get("产地") or ""
    if not mainland(origin):
        return []
    slug = url.rsplit("/", 1)[-1].split(".")[0]
    date = f"{slug[:4]}-{slug[4:6]}-{slug[6:8]}"
    head = title(page)
    item = next((t[k] for k in t if re.search(r"不符合检测项目|除害剂名称|金属杂质名称|名称$", k) and k not in ("产品名称", "食物名称")), "")
    found = next((t[k] for k in t if "含量" in k and ("验出" in k or "检测" in k or "检出" in k)), "")
    limit = next((t[k] for k in t if re.search(r"限量|上限|标示含量|法定", k)), "")
    detail = head
    if item:
        detail += "。项目：" + item.strip().replace("\n", "、")
    if found:
        detail += "，检出：" + found.strip().replace("\n", "、")
    note = []
    for k in ("品牌", "净重", "此日期前最佳", "此日期或之前食用", "抽取样本地点"):
        if t.get(k):
            note.append(f"{k}：" + t[k].replace("\n", " "))
    note.append("原产地：" + origin)
    if t.get("备注"):
        note.append("备注：" + t["备注"].strip().split("\n")[0])
    return [{
        "id": f"HK-US-{slug}", "src": "HK", "pub_date": date, "insp_date": None, "grp": "食品", "ind": "",
        "ntype": "违规样本", "product": t.get("产品名称") or t.get("食物名称") or "", "product_orig": "",
        "problems": _types(head, item, limit), "detail": detail,
        "legal_limit": limit.strip().replace("\n", "、"), "quantity": "", "firm": t.get("制造商") or t.get("生产商") or "",
        "importer": t.get("进口商") or t.get("分销商") or "", "lab_tested": True, "entry_no": "", "action": "停售",
        "note": "；".join(note)[:800], "url": url, "raw": {"table": t, "title": head}, "machine_translated": False,
    }]


def fetch(since_year, known=(), delay=0.5, log=print):
    """Records from since_year on. Pages whose ids are in known are skipped (they never change)."""
    known = set(known)
    recs, pages = [], 0
    for y in range(since_year, datetime.date.today().year + 1):
        for u in alert_urls(y):
            slug = u.rsplit("/", 1)[-1].split(".")[0]
            if any(k.startswith(f"HK-FA-{slug}-") for k in known) or f"HK-FA-{slug}" in known:
                continue
            recs += parse_alert(u, get(u))
            pages += 1
            time.sleep(delay)
    for y, mo in months():
        if y < since_year:
            continue
        for u in sample_urls(y, mo):
            slug = u.rsplit("/", 1)[-1].split(".")[0]
            if f"HK-US-{slug}" in known:
                continue
            recs += parse_sample(u, get(u))
            pages += 1
            time.sleep(delay)
        time.sleep(delay)
    log(f"  HK: read {pages} pages ({VIA_DB[0]} through the database), {len(recs)} mainland records")
    return recs

