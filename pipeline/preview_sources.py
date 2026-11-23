"""Dry run for new sources: fetch + parse, write JSON files, touch nothing in the database."""
import json
import os
import sys

from . import hk

out = sys.argv[1] if len(sys.argv) > 1 else "out"
os.makedirs(out, exist_ok=True)
recs = hk.fetch(2020)
json.dump(recs, open(os.path.join(out, "hk.json"), "w"), ensure_ascii=False, indent=1, default=str)
print("hk", len(recs))
