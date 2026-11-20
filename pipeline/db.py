"""Storage layer.
With SUPABASE_URL and SUPABASE_SERVICE_KEY set: uses Supabase (PostgREST API).
Without them: uses a local file local_data/records.jsonl (for testing on your own computer).
"""
import json
import os

import requests

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "local_data", "records.jsonl")


def using_supabase():
    return bool(URL and KEY)


def _h(extra=None):
    h = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
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
    """All records, newest first."""
    if using_supabase():
        out, step = [], 1000
        while True:
            r = requests.get(f"{URL}/rest/v1/records?select={columns}&order=pub_date.desc,id.asc",
                             headers=_h({"Range-Unit": "items", "Range": f"{len(out)}-{len(out) + step - 1}"}), timeout=120)
            r.raise_for_status()
            batch = r.json()
            out += batch
            if len(batch) < step:
                return out
    return sorted(_load_local().values(), key=lambda r: (r["pub_date"], r["id"]), reverse=True)


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
