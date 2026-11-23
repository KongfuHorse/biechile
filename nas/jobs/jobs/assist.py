"""Searches on pages that ask for a human check (slider).

The browser runs on the NAS's virtual screen, which a person can see and use through the
noVNC page. When the check appears, this job waits; the person finishes it by hand; then the
job carries on. It never moves the slider itself.
"""
import json
import os
import re
import time

from .probe import UA, _archive, _settle

CHECK = re.compile(r"请完成下列验证|拖动|滑块|拼图")


def _shows_check(page):
    try:
        return bool(CHECK.search(page.inner_text("body")))
    except Exception:
        return False


def spcj_search(args, ctx):
    """National food sampling result search (spcjsac.gsxt.gov.cn), by company name.
    args: {"names": [...], "tab": "企业名称", "human_wait_s": 600, "pause_s": 5}
    For each name: search, wait for a person if the check appears, keep every data response.
    Reports, per name, whether the check appeared and how long the person took."""
    from playwright.sync_api import sync_playwright
    headed = bool(os.environ.get("DISPLAY"))
    out = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=not headed, args=["--no-sandbox", "--disable-dev-shm-usage", "--start-maximized"])
        page = b.new_context(user_agent=UA, locale="zh-CN", viewport={"width": 1340, "height": 820}).new_page()
        got = []

        def on_response(r):
            if r.request.resource_type in ("xhr", "fetch") and "getSlideImage" not in r.url:
                try:
                    body = r.text()
                except Exception:
                    body = ""
                got.append({"url": r.url, "method": r.request.method, "post": (r.request.post_data or "")[:3000],
                            "status": r.status, "body": body[:200000]})

        page.on("response", on_response)
        page.goto("https://spcjsac.gsxt.gov.cn/", wait_until="domcontentloaded", timeout=45000)
        _settle(page, 10000)
        page.click("text=" + args.get("tab", "企业名称"), timeout=15000)
        for name in args.get("names", []):
            got.clear()
            item = {"name": name, "check": False, "human_seconds": None}
            page.fill("input", name, timeout=15000)
            page.click("text=搜索", timeout=15000)
            page.wait_for_timeout(2500)
            if _shows_check(page):
                item["check"] = True
                ctx.log.info("%s: human check shown, waiting for a person", name)
                t = time.time()
                while _shows_check(page) and time.time() - t < int(args.get("human_wait_s", 600)):
                    page.wait_for_timeout(1500)
                item["human_seconds"] = round(time.time() - t)
                if _shows_check(page):
                    item["error"] = "no one finished the check in time"
                    out.append(item)
                    break
            _settle(page, 10000)
            page.wait_for_timeout(1500)
            item["responses"] = list(got)
            item["text"] = re.sub(r"\s+", " ", page.inner_text("body"))[:4000]
            item["saved"] = _archive(ctx, "spcj:" + name, page.content())
            ctx.log.info("%s: check=%s, %d responses", name, item["check"], len(got))
            out.append(item)
            time.sleep(float(args.get("pause_s", 5)))
        if args.get("screenshot", True):
            ctx.put_file("last.jpg", "image/jpeg", page.screenshot(type="jpeg", quality=50, full_page=True))
        b.close()
    return {"headed": headed, "results": out}
