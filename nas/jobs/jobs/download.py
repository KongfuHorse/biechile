"""Plain downloads of public pages and the documents they link to (no browser).

A page comes back as text. Documents linked from it (xlsx, docx, pdf ...) are sent back as job
files, so they can be read elsewhere. Copies of everything are kept on the NAS.
"""
import hashlib
import os
import re
import time
from urllib.parse import unquote, urljoin

import requests

from .probe import UA, _archive

DOC = re.compile(r"\.(xlsx|xls|docx|doc|pdf|et|wps|zip|rar)(?:[?#]|$)", re.I)
MIME = {"xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xls": "application/vnd.ms-excel",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "doc": "application/msword",
        "pdf": "application/pdf"}


def _keep(ctx, url, data, ext):
    d = os.path.join(ctx.data_dir, "files", time.strftime("%Y-%m-%d"))
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, hashlib.sha1(url.encode()).hexdigest() + "." + ext)
    with open(p, "wb") as f:
        f.write(data)


def pages(args, ctx):
    """args: {"urls": [...], "docs": true, "delay": 1.5, "max_doc_mb": 3}"""
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    out, nfile = [], 0
    for u in args.get("urls", []):
        item = {"url": u, "docs": []}
        try:
            r = s.get(u, timeout=60)
            if r.encoding in (None, "ISO-8859-1"):
                r.encoding = r.apparent_encoding
            html = r.text
            item.update({"status": r.status_code, "html": html, "saved": _archive(ctx, u, html)})
            if args.get("docs", True):
                seen = set()
                for href, label in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
                    if not DOC.search(href):
                        continue
                    du = urljoin(u, href.replace("&amp;", "&"))
                    if du in seen:
                        continue
                    seen.add(du)
                    name = re.sub(r"<[^>]+>|\s+", " ", label).strip() or unquote(du.split("/")[-1].split("?")[0])
                    ext = DOC.search(href).group(1).lower()
                    time.sleep(float(args.get("delay", 1.5)))
                    d = {"url": du, "name": name[:200], "ext": ext}
                    try:
                        f = s.get(du, timeout=90, headers={"Referer": u})
                        d.update({"status": f.status_code, "bytes": len(f.content)})
                        if f.ok and len(f.content) <= float(args.get("max_doc_mb", 3)) * 1e6:
                            _keep(ctx, du, f.content, ext)
                            nfile += 1
                            d["file"] = f"f{nfile:03d}.{ext}"
                            ctx.put_file(d["file"], MIME.get(ext, "application/octet-stream"), f.content)
                    except Exception as e:
                        d["error"] = str(e)[:200]
                    item["docs"].append(d)
        except Exception as e:
            item["error"] = str(e)[:300]
        ctx.log.info("pages %s -> %s, %d docs", u, item.get("status", item.get("error")), len(item["docs"]))
        out.append(item)
        time.sleep(float(args.get("delay", 1.5)))
    return {"results": out}
