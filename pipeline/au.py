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
    for attempt in range(4):
        try:
            r = requests.get(url, headers=UA, timeout=90, **kw)
            r.raise_for_status()
            if url.lower().endswith(".csv") and r.content.lstrip()[:1] == b"<":
                raise requests.HTTPError(f"got a web page instead of the CSV: {url}")
            return r
        except (requests.ConnectionError, requests.Timeout) as e:
            if attempt == 3:
                raise Blocked(f"{url}: {type(e).__name__}") from e
        except requests.HTTPError:
            if attempt == 3:
                raise
        time.sleep(10 * (attempt + 1))


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


HEAD = [  # header text -> field; first match wins, checked in this order
    ("date", r"date of fail"), ("product", r"product"), ("country", r"count?r?y\s+of\s+origin"),
    ("producer", r"producer"), ("both", r"test applied\s*/\s*reason|test applied/"), ("test", r"^test applied$"),
    ("reason", r"reason for fail"), ("units", r"^units$"), ("result", r"result"),
    ("criteria", r"reference|standard"), ("category", r"categ"), ("ho", r"holding order"),
]
DEFAULT = {"date": 0, "product": 1, "country": 2, "producer": 3, "both": 4, "result": 5, "criteria": 6, "category": 7}


def _columns(head):
    cols = {}
    for i, h in enumerate(c.lower().strip() for c in head):
        for key, pat in HEAD:
            if key not in cols and re.search(pat, h):
                cols[key] = i
                break
    has_reason = any(k in cols for k in ("both", "reason", "test"))
    return cols if "date" in cols and "product" in cols and has_reason else None


def parse(text):
    recs, cols, section = [], DEFAULT, ""
    for row in csv.reader(io.StringIO(text)):
        cells = [re.sub(r"\s+", " ", c).strip() for c in row]
        if not any(cells):
            continue
        got = (lambda k: cells[cols[k]] if k in cols and cols[k] < len(cells) else "")
        if any(re.search(r"date of fail", c, re.I) for c in cells):
            cols = _columns(cells) or DEFAULT
            continue
        date = _date(got("date"))
        if not date:
            filled = [c for c in cells if c]
            if len(filled) == 1 and not got("date") and not recs or (len(filled) == 1 and cells[0]):
                section = filled[0]  # a title row such as "Risk food tests"
                continue
            if not got("date") and recs:  # another test on the product above
                last = recs[-1]
                reason = got("both") or got("reason") or got("test")
                result = " ".join(x for x in (got("result"), got("units")) if x and x.lower() not in ("n/a", "na"))
                if reason:
                    last["reason"] = "；".join(x for x in (last["reason"], reason) if x)
                if result:
                    last["result"] = ", ".join(x for x in (last["result"].rstrip(", "), result.rstrip(", ")) if x)
            continue
        test, reason = got("test"), got("reason")
        if got("both"):
            reason = got("both")
        elif test and reason and test.lower() not in reason.lower():
            reason = f"{test}: {reason}"
        else:
            reason = reason or test
        units = got("units")
        result = got("result")
        if units and units.lower() not in ("n/a", "na") and result.lower() not in ("n/a", "na", ""):
            result = f"{result} {units}"
        recs.append({"date": date, "product": got("product"), "country": got("country"), "producer": got("producer"),
                     "reason": reason, "result": result, "criteria": got("criteria"),
                     "category": got("category") or section})
    return recs


def fetch(since):
    out = []
    for month, res in reports(since):
        try:
            text = _text(_get(res["url"]).content)
        except Exception as e:  # one month failing should not stop the rest; the daily run retries recent months
            print(f"  AU {month:%Y-%m} skipped: {type(e).__name__}: {e}"[:200], flush=True)
            continue
        for r in parse(text):
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
    kind = "风险食品检查" if "risk" in cat else "随机监测" if "surv" in cat else ""
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
