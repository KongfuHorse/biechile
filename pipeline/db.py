"""Storage layer.
With SUPABASE_URL and SUPABASE_SERVICE_KEY set: uses Supabase (PostgREST API).
Without them: uses a local file local_data/records.jsonl (for testing on your own computer).
"""
import json
import os
import re

import requests

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "local_data", "records.jsonl")


def using_supabase():
    return bool(URL and KEY)


def _h(extra=None):
    h = {"apikey": KEY, "Content-Type": "application/json"}
    if not KEY.startswith("sb_"):  # legacy service_role JWT also goes in Authorization; new sb_secret_ keys must not
        h["Authorization"] = f"Bearer {KEY}"
    h.update(extra or {})
    return h


def _load_local():
    if not os.path.exists(LOCAL):
        return {}
    with open(LOCAL, encoding="utf-8") as f:
        return {r["id"]: r for r in map(json.loads, f) if r}


def upsert(records):
    """Insert new records or update existing ones (matched by id). Returns count."""
    if not records:
        return 0
    if using_supabase():
        for i in range(0, len(records), 500):
            r = requests.post(f"{URL}/rest/v1/records?on_conflict=id", json=records[i:i + 500],
                              headers=_h({"Prefer": "resolution=merge-duplicates,return=minimal"}), timeout=120)
            r.raise_for_status()
        return len(records)
    data = _load_local()
    for r in records:
        old = data.get(r["id"])
        r.setdefault("first_seen", old["first_seen"] if old else None)
        data[r["id"]] = r
    os.makedirs(os.path.dirname(LOCAL), exist_ok=True)
    with open(LOCAL, "w", encoding="utf-8") as f:
        for r in data.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(records)


def fetch_all(columns="*"):
    """All records, newest first.

    Pages continue from the last row of the previous page (pub_date, id) instead of skipping N rows:
    skipping made the last pages scan the whole table and hit the database time limit."""
    if using_supabase():
        out, step, after, total = [], 1000, None, None
        cols = columns if columns == "*" or re.search(r"(^|,)pub_date(,|$)", columns) else "pub_date," + columns
        if not re.search(r"(^|,)id(,|$)", cols) and cols != "*":
            cols = "id," + cols
        while True:
            q = {"select": cols, "order": "pub_date.desc,id.asc", "limit": str(step)}
            if after:
                d, i = after
                i = '"' + i.replace("\\", "\\\\").replace('"', '\\"') + '"'
                q["or"] = f"(pub_date.lt.{d},and(pub_date.eq.{d},id.gt.{i}))"
            r = requests.get(f"{URL}/rest/v1/records", params=q,
                             headers=_h({"Prefer": "count=exact"} if total is None else {}), timeout=120)
            r.raise_for_status()
            if total is None:
                total = int(r.headers.get("Content-Range", "*/-1").split("/")[-1])
            batch = r.json()
            out += batch
            if len(batch) < step:
                if total >= 0 and len(out) != total:
                    raise RuntimeError(f"fetch_all read {len(out)} records but the table has {total}")
                return out
            after = (batch[-1]["pub_date"], batch[-1]["id"])
    return sorted(_load_local().values(), key=lambda r: (r["pub_date"], r["id"]), reverse=True)


def fetch_table(name, select="*", query=""):
    """Read a whole table in pages of 1000 (Supabase only; returns [] in local mode)."""
    if not using_supabase():
        return []
    out, step = [], 1000
    while True:
        r = requests.get(f"{URL}/rest/v1/{name}?select={select}{query}",
                         headers=_h({"Range-Unit": "items", "Range": f"{len(out)}-{len(out) + step - 1}"}), timeout=120)
        r.raise_for_status()
        rows = r.json()
        out += rows
        if len(rows) < step or "limit=" in query:
            return out


def update(record_id, fields):
    """Change some columns of one record."""
    if not using_supabase():
        rec = _load_local().get(record_id)
        if rec:
            rec.update(fields)
            upsert([rec])
        return
    r = requests.patch(f"{URL}/rest/v1/records?id=eq.{requests.utils.quote(record_id, safe='')}", json=fields,
                       headers=_h({"Prefer": "return=minimal"}), timeout=60)
    r.raise_for_status()


def ids(src):
    """All record ids of one source."""
    if not using_supabase():
        return {i for i, r in _load_local().items() if r.get("src") == src}
    out, step = set(), 1000
    while True:
        r = requests.get(f"{URL}/rest/v1/records?select=id&src=eq.{src}&order=id",
                         headers=_h({"Range-Unit": "items", "Range": f"{len(out)}-{len(out) + step - 1}"}), timeout=120)
        r.raise_for_status()
        rows = r.json()
        out |= {x["id"] for x in rows}
        if len(rows) < step:
            return out


def oldest_tw():
    """(id, publish date) of the oldest Taiwan notice stored, or (0, None)."""
    if not using_supabase():
        return 0, None
    r = requests.get(f"{URL}/rest/v1/records?select=pub_date,tid:raw->>id&src=eq.TW&order=pub_date.asc&limit=50",
                     headers=_h(), timeout=60)
    r.raise_for_status()
    rows = [x for x in r.json() if x.get("tid")]
    return (min(int(x["tid"]) for x in rows), rows[0]["pub_date"]) if rows else (0, None)


def max_tw_id():
    """Highest Taiwan notice id already stored (0 if none)."""
    if using_supabase():
        r = requests.get(f"{URL}/rest/v1/records?select=raw->>id&src=eq.TW&order=pub_date.desc&limit=50",
                         headers=_h(), timeout=60)
        r.raise_for_status()
        ids = [int(x["id"]) for x in r.json() if x.get("id")]
        return max(ids) if ids else 0
    ids = [int(r["id"].split("-")[1]) for r in _load_local().values() if r["src"] == "TW"]
    return max(ids) if ids else 0


def log_run(source, fetched, upserted, status, note=""):
    print(f"[{source}] fetched={fetched} upserted={upserted} status={status} {note}")
    if using_supabase():
        requests.post(f"{URL}/rest/v1/runs", json={"source": source, "fetched": fetched, "upserted": upserted,
                                                   "status": status, "note": note[:2000]},
                      headers=_h({"Prefer": "return=minimal"}), timeout=60)
