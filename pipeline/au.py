"""Australia, Department of Agriculture: Imported Food Inspection Scheme failing food reports.

The department publishes each monthly report as a CSV on data.gov.au (open data, CKAN API).
Imported food that failed testing at the border is not sold in Australia; it is destroyed or
sent back. We keep rows whose country of origin is China.

The column names change between months but the order stays the same:
date, product, country of origin, producer, test applied / reason for fail, result, reference, category.
A product that failed several tests has extra rows below it with only the test and result filled in.
"""
import csv
import datetime as dt
import hashlib
import io
import re
import time

import requests

PKG = "e56bcf6a-7bfb-4cb5-8c65-8ec18bd4b7d5"
API = "https://data.gov.au/data/api/3/action/package_show"
PAGE = "https://data.gov.au/data/dataset/" + PKG + "/resource/"
UA = {"User-Agent": "biechile.com data collector"}
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
FIELDS = ["date", "product", "country", "producer", "reason", "result", "criteria", "category"]


class Blocked(Exception):
    """The site did not answer this server."""


def _get(url, **kw):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=60, **kw)
            r.raise_for_status()
            return r
        except (requests.ConnectionError, requests.Timeout) as e:
            if attempt == 2:
                raise Blocked(f"{url}: {type(e).__name__}") from e
            time.sleep(5 * (attempt + 1))


def reports(since):
    """Monthly CSV files from the month of since onward: [(first day of month, resource)]."""
    d0 = dt.date.fromisoformat(since).replace(day=1)
    out = {}
    for res in _get(API, params={"id": PKG}).json()["result"]["resources"]:
        m = re.search(r"(" + "|".join(MONTHS) + r")\s+(\d{4})", res.get("name", ""), re.I)
        is_csv = (res.get("format") or "").lower() == "csv" or res.get("url", "").lower().endswith(".csv")
        if m and is_csv:
            month = dt.date(int(m.group(2)), MONTHS[m.group(1).lower()], 1)
            if month >= d0:
                out[month] = res  # a later upload for the same month replaces the earlier one
    return sorted(out.items())


def _date(s):
    s = s.strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    if re.fullmatch(r"\d{5}(\.0)?", s):  # Excel day number
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(float(s)))).isoformat()
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)", s)
    return m.group(0) if m else None


def _text(raw):
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace")


def parse(text):
    recs = []
    for row in csv.reader(io.StringIO(text)):
        cells = [re.sub(r"\s+", " ", c).strip() for c in row[:8]]
        cells += [""] * (8 - len(cells))
        if not any(cells):
            continue
        date = _date(cells[0])
        if date:
            recs.append(dict(zip(FIELDS, cells), date=date))
        elif not cells[0] and recs:  # another test on the product above
            last = recs[-1]
            if cells[4]:
                last["reason"] = "；".join(x for x in (last["reason"], cells[4]) if x)
            if cells[5]:
                last["result"] = ", ".join(x for x in (last["result"].rstrip(", "), cells[5].rstrip(", ")) if x)
        # anything else is a header row
    return recs


def fetch(since):
    out = []
    for month, res in reports(since):
        for r in parse(_text(_get(res["url"]).content)):
            if re.fullmatch(r"(people'?s republic of )?china", r["country"], re.I) and r["date"] >= since:
                r["url"] = PAGE + res["id"]
                r["report"] = f"{month.year}-{month.month:02d}"
                out.append(r)
        time.sleep(0.3)
    return out


def rec_id(r):
    key = "|".join(r.get(k, "") for k in ("date", "product", "producer", "reason", "result"))
    return "AU-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:14]


def detail_text(r):
    return r.get("reason", "")


def normalize(r, tr):
    cat = r.get("category", "").lower()
    kind = "风险食品检查" if cat.startswith("risk") else "随机监测" if cat.startswith("surv") else ""
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
