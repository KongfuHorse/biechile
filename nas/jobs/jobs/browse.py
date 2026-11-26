"""Download pages with a real browser, for sites that refuse plain downloads (403 without browser cookies).

args: {"urls": [...], "delay": 2, "wait_ms": 8000, "docs": true, "max_doc_mb": 8}
Each page's HTML is stored with put_file as p001.html, p002.html, ...; documents the page links to
(xlsx, xls, doc, docx, pdf) are fetched with the same browser session as f001.xlsx, ...
Returns {"results": [{url, status, title, file, docs: [{url, name, ext, status, bytes, file}]}]}.
Like the other handlers it only reads public pages and never tries to solve a captcha.
"""
import re
import time
from urllib.parse import urljoin

from .probe import UA, _browser, _open, _read

DOC = re.compile(r"\.(xlsx|xls|docx|doc|pdf)(\?|$)", re.I)


def browse(args, ctx):
    from playwright.sync_api import sync_playwright
    out, nf, npg = [], 0, 0
    with sync_playwright() as p:
        b = _browser(p)
        bc = b.new_context(user_agent=UA, locale="zh-CN", viewport={"width": 1280, "height": 900})
        page = bc.new_page()
        for u in args.get("urls", []):
            item = {"url": u}
            try:
                resp = _open(page, u, int(args.get("wait_ms", 8000)))
                item["status"] = resp.status if resp else None
                html, _ = _read(page)
                item["title"] = page.title()
                npg += 1
                item["file"] = f"p{npg:03d}.html"
                ctx.put_file(item["file"], "text/html", html.encode("utf-8"))
                docs = []
                if args.get("docs"):
                    seen = set()
                    for href, label in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
                        if not DOC.search(href):
                            continue
                        du = urljoin(page.url, href.replace("&amp;", "&"))
                        if du in seen:
                            continue
                        seen.add(du)
                        d = {"url": du, "name": re.sub(r"<[^>]+>|\s+", "", label)[:120], "ext": DOC.search(href).group(1).lower()}
                        try:
                            r = bc.request.get(du, timeout=90000)
                            body = r.body()
                            d["status"], d["bytes"] = r.status, len(body)
                            if r.ok and len(body) <= float(args.get("max_doc_mb", 8)) * 1e6:
                                nf += 1
                                d["file"] = f"f{nf:03d}.{d['ext']}"
                                ctx.put_file(d["file"], "application/octet-stream", body)
                        except Exception as e:
                            d["error"] = str(e)[:200]
                        docs.append(d)
                        time.sleep(1)
                item["docs"] = docs
            except Exception as e:
                item["error"] = str(e)[:300]
            out.append(item)
            ctx.log.info("browse %s -> %s", u, item.get("status") or item.get("error"))
            time.sleep(float(args.get("delay", 2)))
        b.close()
    return {"results": out}
