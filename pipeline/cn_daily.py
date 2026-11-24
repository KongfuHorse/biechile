"""Daily mainland step (the NAS in China does the downloading; this runs on GitHub).

1. Parse notice pages the NAS downloaded in the last few days into cn_checks.
2. Read the newest list pages the NAS downloaded and ask it to download notices not seen before.
3. Ask the NAS to download the list pages again, for tomorrow's run.

So a new notice reaches the website one or two days after it is published.
"""
import datetime
import json
import re

import requests

from . import cn_more, cn_samr, db

SAMR = "https://www.samr.gov.cn"
LISTS = [
    # SAMR food sampling notices (食品抽检)
    (SAMR + "/api-gateway/jpaas-publish-server/front/page/build/unit?webId=29e9522dc89d4e088a953d8cede72f4c&pageId=c50b450d9afa44e2a7f83f0c2a0c5ffc"
     "&parseType=bulidstatic&pageType=column&tagId=%E5%86%85%E5%AE%B9%E5%8C%BA%E5%9F%9F&tplSetId=5c30fb89ae5e48b9aefe3cdf49853830"
     '&paramJson={"pageNo":1,"pageSize":30}'),
    # SAMR national product quality spot checks (监督抽查不合格产品发布, 本司公告)
    cn_more.LIST_SAMR.format(pid=cn_more.SAMR_COLUMNS[0], n=1).replace('"pageSize":100', '"pageSize":30'),
    cn_more.LIST_SAMR.format(pid=cn_more.SAMR_COLUMNS[1], n=1).replace('"pageSize":100', '"pageSize":30'),
    cn_more.SZ_FOOD + "index.html",
    cn_more.SZ_QUAL + "index.html",
]
RESULTS = re.compile(r"抽查|抽检|抽样检验")
NOT_RESULTS = re.compile(r"计划|遴选|征求|实施规范|细则|目录")


def _rest(path, **kw):
    r = requests.request(kw.pop("method", "GET"), f"{db.URL}/rest/v1/{path}", headers=db._h(kw.pop("headers", None)), timeout=120, **kw)
    r.raise_for_status()
    return r.json() if r.text else None


def wanted(url, title):
    if "/spcjs/art/" in url:
        return True
    if not cn_more.program(url):
        return False
    return bool(RESULTS.search(title)) and not NOT_RESULTS.search(title)


def links(list_url, html):
    html = html.replace('\\"', '"')
    out = []
    for href, title in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>\s*(?:<[^>]+>\s*)*([^<]{6,160})', html):
        u = href if href.startswith("http") else (SAMR + href if href.startswith("/") and "samr" in list_url else None)
        if u:
            out.append((u.split("#")[0], re.sub(r"\s+", "", title)))
    return out


def run(days=3, log=print):
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()

    # 1. parse what arrived
    food, n1, _, _ = cn_samr.collect(since)
    more, n2, _ = cn_more.collect(since)
    if food:
        cn_samr.store(food)
    if more:
        cn_samr.store(more)
    log(f"  CN/SZ: parsed {n1 + n2} downloaded notices, {len(food)} SAMR food rows, {len(more)} other rows")

    # 2. new notices on the latest list pages
    asked = set()
    for j in db.fetch_table("nas_jobs", "args", "&kind=eq.pages"):
        asked |= set((j.get("args") or {}).get("urls") or [])
    lists = _rest(f"nas_jobs?select=id,result&kind=eq.pages&status=eq.done&finished_at=gte.{since}&order=id.desc&args->>lists=eq.1")
    new = []
    for j in lists or []:
        for it in (j.get("result") or {}).get("results", []):
            for u, t in links(it.get("url", ""), it.get("html") or ""):
                if u not in asked and u not in new and wanted(u, t):
                    new.append(u)
    for i in range(0, len(new), 15):
        _rest("nas_jobs", method="POST", headers={"Prefer": "return=minimal"},
              data=json.dumps({"kind": "pages", "args": {"docs": True, "delay": 1.5, "max_doc_mb": 8, "urls": new[i:i + 15]}}))
    log(f"  CN/SZ: asked the NAS for {len(new)} new notices")

    # 3. list pages again for tomorrow
    _rest("nas_jobs", method="POST", headers={"Prefer": "return=minimal"},
          data=json.dumps({"kind": "pages", "args": {"docs": False, "delay": 1.5, "lists": 1, "urls": LISTS}}))
    return len(food) + len(more), len(new)
