"""Daily job.
  python -m pipeline.run                     # daily update: new TW notices + FDA last 30 days, then export
  python -m pipeline.run --since 2023-01-01  # backfill from a date
  python -m pipeline.run --export-only       # only rebuild the website JSON files
"""
import argparse
import os
import sys
import traceback
from datetime import date, timedelta

from . import db, export, normalize, sources

SITE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "site")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="backfill start date YYYY-MM-DD")
    ap.add_argument("--export-only", action="store_true")
    ap.add_argument("--skip", nargs="*", default=[], help="sources to skip: tw us")
    a = ap.parse_args()
    print("storage:", "Supabase" if db.using_supabase() else "local file")
    failed = False

    if not a.export_only:
        # Taiwan
        if "tw" not in a.skip:
            try:
                since = a.since or (date.today() - timedelta(days=60)).isoformat()
                stop = 0 if a.since else db.max_tw_id()
                raw = sources.fetch_tw(since, stop_id=stop)
                n = db.upsert([normalize.normalize_tw(r) for r in raw])
                db.log_run("TW", len(raw), n, "ok", f"since={since} stop_id={stop}")
            except Exception:
                failed = True
                db.log_run("TW", 0, 0, "error", traceback.format_exc())
        # US FDA
        if "us" not in a.skip:
            try:
                since = a.since or (date.today() - timedelta(days=30)).isoformat()
                raw = sources.fetch_fda(since)
                n = db.upsert([normalize.normalize_fda(r) for r in raw])
                db.log_run("US", len(raw), n, "ok", f"since={since}")
            except Exception:
                failed = True
                db.log_run("US", 0, 0, "error", traceback.format_exc())

        new_terms = {k: sorted(v) for k, v in normalize.untranslated.items() if v}
        if new_terms:
            db.log_run("terms", 0, 0, "review", f"untranslated: {new_terms}")

    export.run(SITE)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
