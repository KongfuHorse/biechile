"""Zip nas/jobs/jobs, store it in Supabase table nas_code, and tell the agent to use it.

Run by GitHub Actions (or by hand) with SUPABASE_URL and SUPABASE_SERVICE_KEY set.
The zip is built in a fixed order with fixed timestamps, so the same code gives the same sha256,
and publishing the same code twice does nothing.
"""
import base64
import hashlib
import io
import os
import subprocess
import sys
import zipfile

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "jobs")


def build_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(SRC):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for f in sorted(files):
                if f.endswith(".pyc"):
                    continue
                full = os.path.join(root, f)
                info = zipfile.ZipInfo(os.path.relpath(full, SRC), date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, open(full, "rb").read())
    return buf.getvalue()


def main():
    url, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_KEY"]
    h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    raw = build_zip()
    sha = hashlib.sha256(raw).hexdigest()
    version = sha[:12]
    try:
        note = subprocess.run(["git", "log", "-1", "--format=%h %s"], capture_output=True, text=True, cwd=HERE).stdout.strip()
    except OSError:
        note = ""
    r = requests.post(f"{url}/rest/v1/nas_code", headers={**h, "Prefer": "resolution=ignore-duplicates"},
                      json={"version": version, "sha256": sha, "zip_b64": base64.b64encode(raw).decode(), "note": note},
                      timeout=60)
    r.raise_for_status()
    r = requests.patch(f"{url}/rest/v1/nas_config?key=eq.code_version", headers=h, json={"value": version}, timeout=60)
    r.raise_for_status()
    print(f"published code {version} ({len(raw)} bytes)")


if __name__ == "__main__":
    sys.exit(main())
