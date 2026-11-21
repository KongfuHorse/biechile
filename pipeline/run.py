"""Daily job.
  python -m pipeline.run                     # daily update: new TW notices + FDA last 30 days, then export
  python -m pipeline.run --since 2023-01-01  # backfill from a date
  python -m pipeline.run --export-only       # only rebuild the website JSON files
  python -m pipeline.run --skip tw us        # skip sources: tw us jp eu kr
"""
import argparse
import os
import sys
import traceback
from datetime import date, timedelta

from . import db, eu, export, firms, jp, kr, mt, normalize, sources

SITE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "site")


def translate_new_terms():
    """Ask Claude for terms missing from the reference tables, save them, and add them to normalize.MT."""
    examples = {
        "fda_product": normalize._fda_product_zh,
        "fda_industry": normalize.IND_ZH,
        "fda_code": {normalize.CODE_TEXT[c]: zh for c, (zh, _) in normalize.FDA_CODE.items() if c in normalize.CODE_TEXT},
    }
    total = 0
    for kind, terms in normalize.untranslated.items():
        terms = sorted(t for t in terms if t)
        if not terms:
            continue
        if kind == "fda_code":  # translate the statement text, store under the code
            by_text = {f"{c}: {normalize.CODE_TEXT.get(c, c)}": c for c in terms}
            got = mt.translate(kind, list(by_text), examples[kind])
            mapping = {by_text[t]: zh for t, zh in got.items()}
        else:
            mapping = mt.translate(kind, terms, examples[kind])
        mt.save(kind, mapping)
        normalize.MT[kind].update(mapping)
        total += len(mapping)
    for v in normalize.untranslated.values():
        v.clear()
    return total


# Japan, EU and Korea: fetch, translate new text with Claude, store
INTL = {
    "jp": {"days": 60, "fetch": lambda since: jp.fetch(since), "norm": jp.normalize,
           "product": lambda r: r["product"], "detail": lambda r: r.get("violation")},
    "eu": {"days": 30, "fetch": lambda since: eu.fetch(since), "norm": eu.normalize,
           "product": lambda r: eu.product_text(r) or eu.subject(r), "detail": eu.subject},
    "kr": {"days": None, "fetch": lambda since: kr.fetch(), "norm": kr.normalize,
           "product": kr.product_text, "detail": lambda r: r["violation"]},
}


def run_intl(key, since_arg, cache):
    cfg = INTL[key]
    since = since_arg or (date.today() - timedelta(days=cfg["days"] or 0)).isoformat()
    raw = cfg["fetch"](since)
    tr = mt.prepare(key.upper(), raw, cfg["product"], cfg["detail"], cache)
    recs = [cfg["norm"](r, tr(r)) for r in raw]
    recs = list({r["id"]: r for r in recs}.values())
    if since_arg:
        recs = [r for r in recs if r["pub_date"] >= since_arg]
    n = db.upsert(recs)
    untranslated = sum(1 for r in recs if not r["machine_translated"])
    db.log_run(key.upper(), len(raw), n, "ok", f"since={since} untranslated={untranslated}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="backfill start date YYYY-MM-DD")
    ap.add_argument("--export-only", action="store_true")
    ap.add_argument("--skip", nargs="*", default=[], help="sources to skip: tw us jp eu kr")
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
                for kind, m in mt.load_cache().items():
                    normalize.MT.setdefault(kind, {}).update(m)
                recs = [normalize.normalize_fda(r) for r in raw]
                note = f"since={since}"
                if any(normalize.untranslated.values()) and mt.available():
                    done = translate_new_terms()
                    note += f" machine_translated={done}"
                    recs = [normalize.normalize_fda(r) for r in raw]
                n = db.upsert(recs)
                db.log_run("US", len(raw), n, "ok", note)
            except Exception:
                failed = True
                db.log_run("US", 0, 0, "error", traceback.format_exc())

        # Japan, EU, Korea
        cache = None
        for key in ("jp", "eu", "kr"):
            if key in a.skip:
                continue
            try:
                if cache is None:
                    cache = mt.load_cache()
                run_intl(key, a.since, cache)
            except Exception:
                failed = True
                db.log_run(key.upper(), 0, 0, "error", traceback.format_exc())

        # AI candidate Chinese names for top firms (admin page only); a failure here does not fail the run
        if "us" not in a.skip:
            try:
                n = firms.generate_candidates()
                if n:
                    db.log_run("firms", n, n, "ok", "AI candidate names for admin review")
            except Exception:
                db.log_run("firms", 0, 0, "error", traceback.format_exc())

        new_terms = {k: sorted(v) for k, v in normalize.untranslated.items() if v}
        if new_terms:
            db.log_run("terms", 0, 0, "review", f"untranslated: {new_terms}")

    export.run(SITE)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
