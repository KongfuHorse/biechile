"""Fetch raw records from each official source."""
import os
import re
import time

import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (biechile.com food safety notice aggregator)"}

# ---------------- Taiwan TFDA ----------------
TW_BASE = "https://www.fda.gov.tw/UnsafeFood/"
TW_FIELDS = {
    "進口商(公司名稱)": "importer", "進口商(公司地址)": "importer_address", "貨品分類號列": "hs_code",
    "檢驗方法": "test_method", "不合格原因暨檢出量詳細說明": "finding", "法規限量標準": "legal_limit",
    "製造廠或國外負責廠商名稱": "manufacturer", "牌名": "brand", "數量及重量": "quantity",
    "處置情形": "action", "發布日期(西元年月日)": "publish_date", "報驗受理日期(西元年月日)": "inspection_date",
}


def tw_latest_id(s):
    html = s.get(TW_BASE + "UnsafeFood.aspx", timeout=30).text
    return max(int(x) for x in re.findall(r"UnsafeFoodContent\.aspx\?id=(\d+)", html))


def tw_parse(html, rid):
    soup = BeautifulSoup(html, "html.parser")
    h3, ul = soup.find("h3"), soup.select_one("ul.resultList")
    if not h3 or not ul:
        return None
    title = h3.get_text(" ", strip=True)
    rec = {"id": rid, "title": title, "url": f"{TW_BASE}UnsafeFoodContent.aspx?id={rid}"}
    m = re.match(r"(.+?)出口「(.+?)」(?:檢出)?(.*)", title)
    if m:
        rec["origin"], rec["product"], rec["category"] = m.group(1), m.group(2), m.group(3)
    for li in ul.find_all("li"):
        th, td = li.select_one(".RL-th"), li.select_one(".RL-td")
        if th and td:
            key = re.sub(r"\s+", "", th.get_text())
            if key in TW_FIELDS:
                rec[TW_FIELDS[key]] = re.sub(r"\s+", " ", td.get_text(" ", strip=True))
    return rec if rec.get("publish_date") else None


def fetch_tw(since, stop_id=0, delay=0.5, max_misses=200, start_id=None):
    """Walk notice ids from newest (or from start_id) down. Stop at stop_id (already stored) or when dates
    go older than `since`. Returns China-origin records only."""
    s = requests.Session(); s.headers.update(UA)
    rid = start_id if start_id else tw_latest_id(s) + 5
    out, misses, older = [], 0, 0
    while rid > stop_id and misses < max_misses and older < 20:
        try:
            r = s.get(f"{TW_BASE}UnsafeFoodContent.aspx?id={rid}", timeout=30)
            rec = tw_parse(r.text, rid) if r.ok else None
        except requests.RequestException:
            rec = None
        if rec:
            misses = 0
            if rec["publish_date"] >= since:
                older = 0
                if rec.get("origin") == "中國大陸":
                    out.append(rec)
            else:
                older += 1
        else:
            misses += 1
        rid -= 1
        time.sleep(delay)
    return out


# ---------------- US FDA import refusals ----------------
FDA_URL = "https://api-datadashboard.fda.gov/v1/import_refusals"
FDA_COLS = ["RefusalDate", "CountryName", "FirmName", "FEINumber", "City", "IndustryCodeDescription",
            "ProductCode", "ProductCodeDescription", "RefusalCharges", "FDASampleAnalysis",
            "PrivateLabAnalysis", "ShipmentID", "FirmProfile",
            "AddressLine1", "AddressLine2", "State", "ZipCode"]


def fetch_fda(since, country="China"):
    headers = {"Content-Type": "application/json",
               "Authorization-User": os.environ["FDA_USER"], "Authorization-Key": os.environ["FDA_KEY"]}
    rows, start = [], 1
    while True:  # max 5000 rows per response
        body = {"start": start, "rows": 5000, "sort": "RefusalDate", "sortorder": "DESC",
                "filters": {"RefusalDateFrom": [since], "CountryName": [country]}, "columns": FDA_COLS}
        r = requests.post(FDA_URL, json=body, headers=headers, timeout=120)
        r.raise_for_status()
        data = r.json()
        batch = data.get("result") if isinstance(data, dict) else None
        if not batch:
            if isinstance(data, list) or (isinstance(data, dict) and data.get("message") != "Success."):
                raise RuntimeError(f"FDA API error: {str(data)[:300]}")
            break
        rows += batch
        if len(batch) < 5000:
            break
        start += 5000
    return rows
