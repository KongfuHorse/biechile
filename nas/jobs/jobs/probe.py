"""Connectivity and page probes.

All three handlers only read public pages. They wait between sites, and they never try to
solve a captcha or a slider: when a page asks for one, they report it and move on.
"""
import hashlib
import os
import re
import time

import requests
import urllib3

urllib3.disable_warnings()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
CHALLENGE = re.compile(r"\$_ts|412 Precondition|jsl_|__jsluid|acw_sc__", re.I)
CAPTCHA = re.compile(r"验证码|滑块|captcha|请完成安全验证|人机验证", re.I)
BLOCK = re.compile(r"暂不支持访问|accessrestriction|访问受限|拒绝访问", re.I)


def _flags(text):
    f = []
    if CHALLENGE.search(text or ""):
        f.append("js-challenge")
    if CAPTCHA.search(text or ""):
        f.append("captcha")
    if BLOCK.search(text or ""):
        f.append("blocked")
    return f


def _archive(ctx, url, html):
    """Keep the original page on the NAS: raw/YYYY-MM-DD/<sha1>.html plus the URL."""
    day = time.strftime("%Y-%m-%d")
    d = os.path.join(ctx.data_dir, "raw", day)
    os.makedirs(d, exist_ok=True)
    h = hashlib.sha1(html.encode("utf-8", "replace")).hexdigest()
    p = os.path.join(d, h + ".html")
    if not os.path.exists(p):
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"<!-- {url} fetched {time.strftime('%F %T %z')} -->\n" + html)
    return os.path.relpath(p, ctx.data_dir)


def net(args, ctx):
    """args: {"urls": [...]}. Plain HTTP GET, no browser."""
    out = []
    for u in args.get("urls", []):
        t = time.time()
        try:
            r = requests.get(u, headers={"User-Agent": UA}, timeout=25, verify=False)
            body = r.text[:200000]
            out.append({"url": u, "status": r.status_code, "seconds": round(time.time() - t, 2),
                        "bytes": len(r.content), "final_url": r.url, "flags": _flags(body)})
        except Exception as e:
            out.append({"url": u, "error": str(e)[:200], "seconds": round(time.time() - t, 2)})
        ctx.log.info("net %s -> %s", u, out[-1].get("status", out[-1].get("error")))
        time.sleep(float(args.get("delay", 1)))
    return {"results": out}


def _browser(p):
    return p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])


def _settle(page, wait_ms):
    try:
        page.wait_for_load_state("networkidle", timeout=wait_ms)
    except Exception:
        pass


def _open(page, url, wait_ms):
    """Open a page the way a normal browser does. Some sites first serve a small script page
    that sets a cookie and then reloads itself; wait until that reload has finished."""
    resp, last = None, None
    for i in range(3):  # some government sites are slow or drop the first connection
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=60000)
            break
        except Exception as e:
            last = e
            page.wait_for_timeout(5000 * (i + 1))
    else:
        raise last
    _settle(page, wait_ms)
    page.wait_for_timeout(2000)
    _settle(page, wait_ms)
    return resp


def _read(page):
    """Return (html, text); retry while the page is still navigating."""
    last = None
    for _ in range(5):
        try:
            try:
                page.wait_for_load_state("load", timeout=15000)
            except Exception:
                pass  # a slow image or script should not stop us reading what is there
            html = page.content()
            text = page.inner_text("body") if page.query_selector("body") else ""
            return html, text
        except Exception as e:
            last = e
            page.wait_for_timeout(3000)
    raise last


def probe(args, ctx):
    """args: {"urls": [...], "screenshot": true, "delay": 4, "wait_ms": 10000}.
    Opens each URL in headless Chromium, the same way a normal browser does, and reports
    what the page ends up showing."""
    from playwright.sync_api import sync_playwright
    out = []
    with sync_playwright() as p:
        b = _browser(p)
        for i, u in enumerate(args.get("urls", [])):
            ctxb = b.new_context(user_agent=UA, locale="zh-CN", viewport={"width": 1280, "height": 900})
            page = ctxb.new_page()
            t = time.time()
            item = {"url": u}
            try:
                resp = _open(page, u, int(args.get("wait_ms", 10000)))
                html, text = _read(page)
                item.update({"status": resp.status if resp else None, "final_url": page.url,
                             "title": page.title()[:200], "text_chars": len(text), "html_bytes": len(html),
                             "flags": _flags(html + text), "text_head": re.sub(r"\s+", " ", text)[:300],
                             "seconds": round(time.time() - t, 1), "saved": _archive(ctx, u, html)})
                if args.get("screenshot", True):
                    img = page.screenshot(type="jpeg", quality=45, full_page=False)
                    ctx.put_file(f"probe{i:02d}.jpg", "image/jpeg", img)
                    item["screenshot"] = f"probe{i:02d}.jpg"
            except Exception as e:
                item.update({"error": str(e)[:300], "seconds": round(time.time() - t, 1)})
            ctx.log.info("probe %s -> %s %s", u, item.get("status", item.get("error")), item.get("flags", ""))
            out.append(item)
            ctxb.close()
            time.sleep(float(args.get("delay", 4)))
        b.close()
    return {"results": out}


def fetch(args, ctx):
    """args: {"url": ..., "html": false, "max_chars": 200000, "wait_ms": 10000, "screenshot": false}.
    Opens one page and returns its visible text (and HTML if asked)."""
    from playwright.sync_api import sync_playwright
    u = args["url"]
    with sync_playwright() as p:
        b = _browser(p)
        page = b.new_context(user_agent=UA, locale="zh-CN", viewport={"width": 1280, "height": 900}).new_page()
        resp = _open(page, u, int(args.get("wait_ms", 10000)))
        html, text = _read(page)
        n = int(args.get("max_chars", 200000))
        res = {"url": u, "status": resp.status if resp else None, "final_url": page.url, "title": page.title(),
               "flags": _flags(html + text), "text": text[:n], "saved": _archive(ctx, u, html)}
        if args.get("html"):
            res["html"] = html[:n]
        if args.get("screenshot"):
            ctx.put_file("page.jpg", "image/jpeg", page.screenshot(type="jpeg", quality=50, full_page=True))
        links = page.eval_on_selector_all("a[href]", "els => els.map(e => [e.innerText.trim().slice(0,80), e.href])")
        res["links"] = links[: int(args.get("max_links", 300))]
        b.close()
    ctx.log.info("fetch %s -> %s, %d chars", u, res["status"], len(res["text"]))
    return res


def capture(args, ctx):
    """Open a page, do a few user steps, and record the data requests the page makes.
    args: {"url": ..., "steps": [{"click": sel} | {"fill": [sel, text]} | {"press": [sel, key]} | {"wait": ms}],
           "match": "substring a request URL must contain (optional)", "body_chars": 20000, "screenshot": true}
    Only XHR/fetch requests are kept. Used to learn how a search page gets its results."""
    from playwright.sync_api import sync_playwright
    reqs = []
    with sync_playwright() as p:
        b = _browser(p)
        page = b.new_context(user_agent=UA, locale="zh-CN", viewport={"width": 1280, "height": 900}).new_page()

        def on_response(r):
            q = r.request
            if q.resource_type not in ("xhr", "fetch"):
                return
            if args.get("match") and args["match"] not in r.url:
                return
            item = {"url": r.url, "method": q.method, "status": r.status, "post": (q.post_data or "")[:5000],
                    "req_headers": {k: v for k, v in q.headers.items() if k.lower() in ("content-type", "referer", "x-requested-with")},
                    "type": r.headers.get("content-type", "")}
            try:
                item["body"] = r.text()[: int(args.get("body_chars", 20000))]
            except Exception as e:
                item["body_error"] = str(e)[:200]
            reqs.append(item)

        page.on("response", on_response)
        _open(page, args["url"], int(args.get("wait_ms", 10000)))
        done = []
        for st in args.get("steps", []):
            try:
                if "click" in st:
                    page.click(st["click"], timeout=15000)
                elif "fill" in st:
                    page.fill(st["fill"][0], st["fill"][1], timeout=15000)
                elif "press" in st:
                    page.press(st["press"][0], st["press"][1], timeout=15000)
                elif "wait" in st:
                    page.wait_for_timeout(int(st["wait"]))
                done.append({"step": st, "ok": True})
            except Exception as e:
                done.append({"step": st, "ok": False, "error": str(e)[:300]})
            _settle(page, 8000)
        html, text = _read(page)
        if args.get("screenshot", True):
            ctx.put_file("after.jpg", "image/jpeg", page.screenshot(type="jpeg", quality=50, full_page=True))
        res = {"final_url": page.url, "steps": done, "requests": reqs,
               "text": re.sub(r"\s+", " ", text)[: int(args.get("text_chars", 5000))], "saved": _archive(ctx, args["url"], html)}
        b.close()
    ctx.log.info("capture %s: %d requests", args["url"], len(reqs))
    return res
