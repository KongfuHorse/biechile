"""Australia, Department of Agriculture: failing food reports (Imported Food Inspection Scheme).

One HTML page per month with a table of imported food that failed testing at the border.
Failing food is not sold in Australia; it is destroyed or sent back. We keep rows whose
country of origin is China.
"""
import datetime as dt
import hashlib
import html
import re
import time

import requests

BASE = "https://www.agriculture.gov.au"
INDEX = BASE + "/biosecurity-trade/import/goods/food/inspection-testing/failing-food-reports"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0 Safari/537.36 (biechile.com data collector)"}
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
COLS = {"date": "date of fail", "product": "product description", "country": "o(f|) origin", "producer": "producer",
        "reason": "test applied|reason for fail", "result": "result", "criteria": "reference", "category": "food category"}

S = requests.Session()
S.headers.update(UA)


def _get(url):
    for attempt in range(3):
        try:
            r = S.get(url, timeout=60)
            r.raise_for_status()
            r.encoding = "utf-8"
            return r.text
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))


def reports(since):
    """Monthly report pages from the month of since onward: [(date of month, url)]."""
    t = _get(INDEX)
    d0 = dt.date.fromisoformat(since).replace(day=1)
    out = {}
    for href, text in re.findall(r'<a[^>]+href="([^"]*failing-food-reports/[^"#]+)"[^>]*>(.*?)</a>', t, re.S):
        name = html.unescape(re.sub(r"<[^>]+>|​", "", text)).strip().lower()
        m = re.match(r"([a-z]+)\s+(\d{4})$", name)
        if m and m.group(1) in MONTHS:
            month = dt.date(int(m.group(2)), MONTHS[m.group(1)], 1)
            if month >= d0:
                out[month] = href if href.startswith("http") else BASE + href
    return sorted(out.items())


def _cell(c):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()


def _rows(table):
    """Table rows as lists of cell text, with rowspan cells repeated into the rows below."""
    out, carry = [], {}  # carry: column -> [rows left, text]
    for tr in re.findall(r"<tr\b.*?</tr>", table, re.S | re.I):
        cells = re.findall(r"<t([hd])\b([^>]*)>(.*?)</t[hd]>", tr, re.S | re.I)
        row, col = [], 0
        while cells or any(c >= col and v[0] > 0 for c, v in carry.items()):
            if carry.get(col, [0])[0] > 0:
                carry[col][0] -= 1
                row.append(carry[col][1])
            elif cells:
                _, attrs, body = cells.pop(0)
                text = _cell(body)
                m = re.search(r'rowspan="?(\d+)', attrs)
                if m and int(m.group(1)) > 1:
                    carry[col] = [int(m.group(1)) - 1, text]
                row.append(text)
            else:
                row.append("")
            col += 1
        out.append(row)
    return out


def parse(page):
    rows = []
    for table in re.findall(r"<table\b.*?</table>", page, re.S | re.I):
        trs = _rows(table)
        if not trs:
            continue
        head = [h.lower() for h in trs[0]]
        idx = {}
        for key, pat in COLS.items():
            for i, h in enumerate(head):
                if re.search(pat, h) and i not in idx.values():
                    idx[key] = i
                    break
        if "date" not in idx or "country" not in idx:
            continue
        for cells in trs[1:]:
            rec = {k: (cells[i] if i < len(cells) else "") for k, i in idx.items()}
            m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", rec.get("date", ""))
            if not m:
                continue
            rec["date"] = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
            rows.append(rec)
    return rows


def fetch(since):
    out = []
    for month, url in reports(since):
        for r in parse(_get(url)):
            if re.fullmatch(r"(people'?s republic of )?china", r.get("country", "").strip(), re.I) and r["date"] >= since:
                r["url"] = url
                out.append(r)
        time.sleep(0.5)
    return out


def rec_id(r):
    key = "|".join(r.get(k, "") for k in ("date", "product", "producer", "reason", "result"))
    return "AU-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:14]


def detail_text(r):
    return r.get("reason", "")


def normalize(r, tr):
    cat = r.get("category", "")
    kind = "风险食品检查" if cat.lower().startswith("risk") else "随机监测" if cat.lower().startswith("surv") else ""
    note = []
    if r.get("result"):
        note.append("检测结果：" + r["result"])
    if r.get("criteria"):
        c = r["criteria"]
        note.append("依据：" + ("澳新食品标准 " + c[3:].strip() if c.upper().startswith("FSC") else c))
    if kind:
        note.append(kind)
    return {
        "id": rec_id(r), "src": "AU", "pub_date": r["date"], "insp_date": None, "grp": "食品", "ind": "",
        "ntype": None, "product": tr.get("product") or r.get("product", ""), "product_orig": r.get("product", ""),
        "problems": tr.get("probs") or ["其他"], "detail": tr.get("detail") or r.get("reason", ""), "legal_limit": "",
        "quantity": "", "firm": r.get("producer", ""), "importer": "", "lab_tested": True, "entry_no": "",
        "action": "销毁或退回原产国", "note": "；".join(note), "url": r["url"], "raw": r,
        "machine_translated": bool(tr.get("product") or tr.get("detail")),
    }
