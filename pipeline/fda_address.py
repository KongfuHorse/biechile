"""English addresses of FDA firms (by FEI number), shown in the admin page under the Chinese address box.

The FDA import refusal API returns the firm's address with each refusal line; we keep the newest one
per FEI in table firm_address. The daily run saves addresses from the lines it fetched; run this module
once to fill older firms:  python -m pipeline.fda_address 2020-01-01
"""
import json
import sys

import requests

from . import db, sources

ADDR = ["AddressLine1", "AddressLine2", "City", "State", "ZipCode", "CountryName"]


def address(row):
    parts = [str(row.get(k) or "").strip() for k in ADDR]
    return ", ".join(p for p in parts if p and p.lower() not in ("null", "none"))


def save(rows):
    """rows: FDA refusal lines, newest first. Returns how many firms were saved."""
    best = {}
    for r in rows:
        fei = str(r.get("FEINumber") or "").strip()
        a = address(r)
        if fei and a and fei not in best:
            best[fei] = a
    items = [{"fei": k, "address_en": v} for k, v in best.items()]
    for i in range(0, len(items), 500):
        r = requests.post(f"{db.URL}/rest/v1/firm_address?on_conflict=fei",
                          headers=db._h({"Prefer": "resolution=merge-duplicates,return=minimal"}),
                          data=json.dumps(items[i:i + 500]), timeout=120)
        r.raise_for_status()
    return len(items)


if __name__ == "__main__":
    since = sys.argv[1] if len(sys.argv) > 1 else "2020-01-01"
    rows = sources.fetch_fda(since)
    print("lines", len(rows), "firms saved", save(rows))
