"""Japan MHLW: imported food violations found at the border (輸入時における食品衛生法違反事例).

MHLW publishes one Excel file per fiscal year (April to March), updated monthly, on
INDEX below. We read the yearly files, keep rows whose 生産国 is 中華人民共和国, and
translate the Japanese text with Claude (marked 机翻 on the site).
"""
import datetime as dt
import hashlib
import io
import re

import openpyxl
import requests
import xlrd

BASE = "https://www.mhlw.go.jp"
INDEX = BASE + "/stf/seisakunitsuite/bunya/kenkou_iryou/shokuhin/yunyu_kanshi/ihan/index.html"
UA = {"User-Agent": "Mozilla/5.0 (biechile.com data collector)"}

COLS = {"品名": "product", "条文": "article", "製造者": "maker", "シッパー": "shipper", "生産国": "country",
        "不適格内容": "violation", "担当検疫所": "station", "輸入者名": "importer", "原因": "cause",
        "措置状況": "action", "備考": "inspection", "公表日": "date"}

ACTION_ZH = [("廃棄、積み戻し等を指示", "责令销毁或退回"), ("全量保管", "全部封存"), ("全量", "全部"),
             ("積み戻し", "退回"), ("積戻し", "退回"), ("食用外転用", "改作非食用"), ("廃棄", "销毁"),
             ("滅却", "销毁"), ("焼却", "焚烧"), ("回収", "召回"), ("等", "等")]
INSPECTION_ZH = {"自主検査": "企业自检", "命令検査": "命令检查", "検査命令": "命令检查", "モニタリング検査": "监测检查",
                 "行政検査": "行政检查", "指導検査": "指导检查", "輸入時検査": "入境检查"}


def year_files():
    """Yearly files from newest to oldest: [(label, url)]."""
    h = requests.get(INDEX, headers=UA, timeout=60)
    h.raise_for_status()
    h.encoding = "utf-8"
    out = []
    for href, text in re.findall(r'<a[^>]+href="([^"]+\.xlsx?)"[^>]*>(.*?)</a>', h.text, re.S):
        t = re.sub(r"<[^>]+>", "", text)
        if "～" in t or t.startswith("輸入時における"):
            out.append((t.split("［")[0].split("[")[0].strip(), href if href.startswith("http") else BASE + href))
    return out


def _cell_date(v, datemode=0):
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, (int, float)) and not isinstance(v, bool) and 30000 < v < 60000:
        return (dt.datetime(1899, 12, 30) + dt.timedelta(days=float(v))).date()
    if isinstance(v, str):
        m = re.search(r"(\d{4})[/\-年.](\d{1,2})[/\-月.](\d{1,2})", v)
        if m:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _rows(content, url):
    if url.endswith(".xls"):
        book = xlrd.open_workbook(file_contents=content)
        for s in book.sheets():
            for i in range(s.nrows):
                yield [xlrd.xldate_as_datetime(c.value, book.datemode) if c.ctype == xlrd.XL_CELL_DATE else c.value
                       for c in s.row(i)]
    else:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
        for ws in wb.worksheets:
            for r in ws.iter_rows(values_only=True):
                yield list(r)


def parse_file(url):
    content = requests.get(url, headers=UA, timeout=120).content
    head, out = None, []
    for r in _rows(content, url):
        cells = [re.sub(r"\s+", "", str(c)) if c is not None else "" for c in r]
        if head is None:
            if "品名" in cells and "生産国" in cells:
                head = {COLS[c]: i for i, c in enumerate(cells) if c in COLS}
            continue
        rec = {k: (r[i] if i < len(r) else None) for k, i in head.items()}
        if not rec.get("product"):
            continue
        rec = {k: (v.strip() if isinstance(v, str) else v) for k, v in rec.items()}
        rec["date"] = _cell_date(rec.get("date"))
        out.append(rec)
    return out


def fetch(since, country="中華人民共和国"):
    """China rows published on or after since (YYYY-MM-DD)."""
    since_d = dt.date.fromisoformat(since)
    out = []
    for label, url in year_files():
        rows = parse_file(url)
        dates = [r["date"] for r in rows if r["date"]]
        for r in rows:
            if (r.get("country") or "").replace(" ", "") == country and r["date"] and r["date"] >= since_d:
                r["file"], r["file_label"] = url, label
                out.append(r)
        if dates and max(dates) < since_d:
            break  # older years are not needed
    return out


def rec_id(r):
    key = "|".join(str(r.get(k) or "") for k in ("date", "product", "maker", "violation", "station", "importer"))
    return "JP-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:14]


def group(r):
    a = (r.get("article") or "").translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    p = r.get("product") or ""
    if "第68条" in a or "第62条" in a or "おもちゃ" in p or "がん具" in p:
        return "玩具"
    if "第18条" in a or "器具" in p or "容器包装" in p:
        return "食品接触材料"
    return "食品"


def action_zh(s):
    s = (s or "").strip()
    for ja, zh in ACTION_ZH:
        s = s.replace(ja, zh)
    return s


def normalize(r, tr):
    """tr: {'product': zh or None, 'detail': zh or None, 'probs': [..] or None} from the translation cache."""
    machine = bool(tr.get("product") or tr.get("detail"))
    insp = INSPECTION_ZH.get(r.get("inspection") or "", r.get("inspection") or "")
    return {
        "id": rec_id(r), "src": "JP", "pub_date": r["date"].isoformat(), "insp_date": None,
        "grp": group(r), "ind": "", "ntype": None,
        "note": "检疫所：" + re.sub(r"\s+", "", r["station"]) if r.get("station") else "",
        "product": tr.get("product") or r["product"], "product_orig": r["product"],
        "problems": tr.get("probs") or ["其他"],
        "detail": tr.get("detail") or r.get("violation") or "", "legal_limit": "",
        "quantity": "", "firm": r.get("maker") or r.get("shipper") or "",
        "importer": re.sub(r"\s+", " ", r.get("importer") or ""),
        "lab_tested": True, "entry_no": "", "action": action_zh(r.get("action")) + (f"（{insp}）" if insp else ""),
        "url": INDEX, "raw": {k: (v.isoformat() if isinstance(v, dt.date) else v) for k, v in r.items()},
        "machine_translated": machine,
    }
