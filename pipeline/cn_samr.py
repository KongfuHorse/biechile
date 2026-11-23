"""Mainland food sampling notices (SAMR): parse the notice pages the NAS downloaded into cn_checks,
then compare the labelled companies with the firms on our overseas list.

Input: rows of nas_jobs (kind 'fetch', done) whose URL is a notice page of the SAMR food sampling column.
Run: python -m pipeline.cn_samr            (parse + store + report)
"""
import json
import re
import sys

import requests

from . import db

NUM = "一二三四五六七八九十百零〇"
ROLE = r"(委托|受委托)?(生产|进口|经销|总经销|代理|总代理|出品|分装|监制|销售|加工|制造|灌装|分销)"
PROV = re.compile(r"^(北京市|天津市|上海市|重庆市|内蒙古自治区|广西壮族自治区|西藏自治区|宁夏回族自治区|新疆维吾尔自治区|新疆生产建设兵团|[一-龥]{2,3}省)")

def cn2int(s):
    d = {c: i for i, c in enumerate("零一二三四五六七八九")}; d["〇"] = 0
    n, cur = 0, 0
    for c in s:
        if c == "百": n += (cur or 1) * 100; cur = 0
        elif c == "十": n += (cur or 1) * 10; cur = 0
        else: cur = d.get(c, 0)
    return n + cur

def header(text):
    h = {}
    m = re.search(r"文号[:：]\s*([^\n]+)", text);  h["no"] = m.group(1).strip() if m else None
    m = re.search(r"发布日期[:：]\s*(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    h["date"] = "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3))) if m else None
    return h

def split_label(label):
    """'A委托B生产的、C进口的X' -> ([(name, role)], product)"""
    firms, rest = [], label
    while True:
        m = re.match(r"(.+?)(?:（[^）]*）)?" + ROLE + r"的[、，]?", rest)
        if not m or len(m.group(1)) > 60: break
        name = m.group(1)
        if "委托" in name and not name.endswith("委托"):
            a, b = name.split("委托", 1)
            firms.append((a.strip("、"), "委托方")); name = b
        name = name.strip("、 ")
        if not re.search(r"(公司|厂|店|社|部|场|坊|行|中心|集团|LLC|LLP|Ltd|Inc|Co\.|S\.A|GmbH|[A-Za-z]{4,})", name) and firms == []:
            break
        firms.append((name, m.group(3)))
        rest = rest[m.end():]
    return firms, rest.strip()

def parse(text, url, title):
    h = header(text)
    body = text
    parts = re.split(r"\n\s*[（(]([%s]{1,5})[)）]" % NUM, body)
    out = []
    for i in range(1, len(parts) - 1, 2):
        no, raw = cn2int(parts[i]), parts[i + 1].strip()
        raw = re.split(r"\n\s*(特此通[报告]|附件|[一二三四五六七八九十]、)", raw)[0].strip()
        raw = re.sub(r"\s*\n\s*", "", raw)
        if "不符合" not in raw and "检出" not in raw and "不合格" not in raw: continue
        first, _, note = raw.partition("。")
        m = re.match(r"(.*?)，(?:其中)?(.*)$", first) if "，其中" not in first else re.match(r"(.*?)，其中(.*)$", first)
        head, problem = (m.group(1), m.group(2)) if m else (first, "")
        seller = platform = origin = None; label = head
        ms = re.match(r"(.*?)销售的[、，]?(?:标称)?(.*)$", head)
        if ms: seller, label = ms.group(1), ms.group(2)
        else:
            ms = re.match(r"(.*?)(自行消毒的|自制的|加工的|制作的|使用的|经营的)(.*)$", head)
            if ms: seller, label = ms.group(1), ms.group(3)
        if seller:
            mp = re.search(r"在(.+?)(?:（[^）]*）)?$", seller)
            if mp and re.search(r"(淘宝|天猫|京东|拼多多|抖音|快手|微信|百度|小红书|苏宁|网|APP|商城|平台)", mp.group(1)):
                platform = mp.group(1); seller = seller[:mp.start()]
            seller = re.sub(r"（(店铺名|经营者|网店|店名)[^）]*）", "", seller).strip("、， ")
        label = re.sub(r"^标称", "", label)
        mo = re.search(r"（标称原产(?:国|地)[:：]\s*([^）]+)）", label)
        if mo: origin = mo.group(1); label = label.replace(mo.group(0), "")
        firms, product = split_label(label)
        maker = next((n for n, r in reversed(firms) if r in ("生产", "加工", "制造", "灌装", "分装")), firms[0][0] if firms else None)
        disputed = bool(re.search(r"异议|假冒|不是.{0,40}(生产|进口|经销)|冒用|仿冒", note))
        out.append({"notice_url": url, "notice_title": title, "notice_no": h["no"], "notice_date": h["date"], "item_no": no,
                    "maker": maker, "maker_role": "；".join("%s:%s" % (r, n) for n, r in firms) or None,
                    "product": product or None, "problem": problem.rstrip("。") or None, "seller": seller or None,
                    "platform": platform, "origin": origin, "disputed": disputed, "dispute_note": note.strip() or None, "raw": raw})
    return out


SUF = re.compile(r"(股份有限公司|有限责任公司|有限公司|集团|公司|厂)$")


def key(n):
    """Company name without bracketed parts, place prefix and company suffix, for matching."""
    n = re.sub(r"[（(].*?[)）]", "", n or "")
    n = re.sub(r"\s", "", n)
    while PROV.match(n):
        n = PROV.sub("", n, 1)
    if len(n) > 8:
        n = re.sub(r"^[一-龥]{2,4}?(市|州|盟|地区)", "", n)
    for _ in range(2):
        n = SUF.sub("", n)
    return n


def notices():
    ids = db.fetch_table("nas_jobs", "id", "&kind=eq.fetch&status=eq.done&args->>url=like.*samr.gov.cn/zw/zfxxgk/fdzdgknr/spcjs/art/*&order=id")
    for row in ids:
        r = requests.get(f"{db.URL}/rest/v1/nas_jobs?select=args,result&id=eq.{row['id']}", headers=db._h(), timeout=120)
        r.raise_for_status()
        j = r.json()[0]
        res = j["result"] or {}
        if res.get("text"):
            yield j["args"]["url"], res.get("title") or "", res["text"]


def store(rows):
    for i in range(0, len(rows), 300):
        r = requests.post(f"{db.URL}/rest/v1/cn_checks?on_conflict=notice_url,item_no",
                          headers=db._h({"Prefer": "resolution=merge-duplicates,return=minimal"}),
                          data=json.dumps(rows[i:i + 300]).encode(), timeout=120)
        if r.status_code >= 400:
            raise RuntimeError(f"cn_checks: {r.status_code} {r.text[:300]}")


def our_firms():
    out = [("verified", f["firm_key"], f["zh_name"]) for f in db.fetch_table("firm_zh", "firm_key,zh_name")]
    for a in db.fetch_table("firm_ai", "firm_key,candidates"):
        out += [("ai-" + (c.get("basis") or ""), a["firm_key"], c.get("name")) for c in a["candidates"] or []]
    tw = {r["firm"] for r in db.fetch_table("records", "firm", "&src=eq.TW&firm=not.is.null")}
    out += [("tw", f, f) for f in tw if re.search(r"[一-龥]", f)]
    return [(k, fk, n) for k, fk, n in out if n and re.search(r"[一-龥]", n)]


def main():
    rows, n_notices, empty = [], 0, []
    for url, title, text in notices():
        n_notices += 1
        got = parse(text, url, title)
        if not got:
            empty.append(f"{title} {url}")
        rows += got
    seen, uniq = set(), []
    for r in rows:
        k = (r["notice_url"], r["item_no"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    store(uniq)
    years = {}
    for r in uniq:
        y = (r["notice_date"] or "?")[:4]
        years[y] = years.get(y, 0) + 1
    print(f"notices {n_notices}, items {len(uniq)}, with maker {sum(1 for r in uniq if r['maker'])}, "
          f"disputed {sum(r['disputed'] for r in uniq)}, by year {dict(sorted(years.items()))}")
    print(f"notices with no parsed items: {len(empty)}")
    for e in empty[:40]:
        print("  EMPTY", e)

    names = {}
    for r in uniq:
        for part in (r["maker_role"] or "").split("；"):
            if ":" in part:
                role, nm = part.split(":", 1)
                names.setdefault(nm, []).append((role, r))
    idx = {}
    for nm in names:
        idx.setdefault(key(nm), []).append(nm)
    print(f"distinct labelled companies: {len(names)}")
    firms = our_firms()
    hit_firms, lines = set(), []
    for kind, fk, n in firms:
        k = key(n)
        if len(k) < 4:
            continue
        for nm in idx.get(k, []):
            hit_firms.add(fk)
            for role, r in names[nm]:
                lines.append(f"MATCH [{kind}] {fk[:50]} | {n} => {nm} | {role} | {r['product']} | {(r['problem'] or '')[:40]} | "
                             f"{r['notice_date']}{' | 有异议/假冒核实' if r['disputed'] else ''} | {r['notice_url']}")
    for line in sorted(set(lines)):
        print(line)
    print(f"matched {len(hit_firms)} of {len({fk for _, fk, _ in firms})} firms on our list that have a Chinese name or candidate")


if __name__ == "__main__":
    sys.exit(main())
