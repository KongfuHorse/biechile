"""Dry run for new sources: fetch + parse, write JSON files, touch nothing in the database.
Usage: python -m pipeline.preview_sources OUT_DIR [hk] [cn]"""
import json
import os
import sys

out = sys.argv[1] if len(sys.argv) > 1 else "out"
what = sys.argv[2:] or ["hk", "cn"]
os.makedirs(out, exist_ok=True)
if "hk" in what:
    from . import hk
    recs = hk.fetch(2020)
    json.dump(recs, open(os.path.join(out, "hk.json"), "w"), ensure_ascii=False, indent=1, default=str)
    print("hk", len(recs), "via db", hk.VIA_DB[0])
if "cn" in what:
    from . import cn_more, cn_site
    rows, n, empty = cn_more.collect()
    json.dump(rows, open(os.path.join(out, "cn_more.json"), "w"), ensure_ascii=False, indent=1, default=str)
    print("cn_more notices", n, "rows", len(rows), "no failed rows", len(empty))
    for u in empty:
        print("  no failed rows:", u)
