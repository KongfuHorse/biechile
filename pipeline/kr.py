"""Korea MFDS: imported food that failed inspection (수입식품부적합).

The official list only keeps about the last six months, so we fetch it every day and keep
what we have seen. Text is Korean and is translated with Claude (marked 机翻 on the site).
"""
import html
import re

import requests

LIST = "https://impfood.mfds.go.kr/CFCEE01F01/getList"
PAGE = "https://impfood.mfds.go.kr/CFCEE01F01"
UA = {"User-Agent": "Mozilla/5.0 (biechile.com data collector)"}

GROUP = {"농.임산물": "食品", "수산물": "食品", "축산물": "食品", "가공식품": "食品", "식품첨가물": "食品",
         "기구또는용기.포장": "食品接触材料", "건강기능식품": "膳食补充剂"}
OFFICE = {"서울청": "首尔食药厅", "부산청": "釜山食药厅", "경인청": "京仁食药厅", "대구청": "大邱食药厅", "광주청": "光州食药厅",
          "대전청": "大田食药厅", "공항": "机场", "인천항": "仁川港", "감천항": "甘川港", "신선대": "神仙台",
          "북항": "北港", "김포": "金浦", "용인": "龙仁", "미추홀": "弥邹忽", "광주": "光州", "평택": "平泽"}


def _span(block, title):
    m = re.search(r'title="' + re.escape(title) + r'"[^>]*>([^<]*)<', block)
    return html.unescape(m.group(1)).strip() if m else ""


def fetch(country="중국"):
    params = {"limit": 1000, "page": 1, "searchCondition": "mCountry", "searchInpText": country, "srchClassCd": ""}
    r = requests.get(LIST, params=params, headers=UA, timeout=120)
    r.raise_for_status()
    return parse(r.text, country)


def parse(text, country="중국"):
    total = int((re.search(r"총 <strong>(\d+)", text) or [0, 0])[1])
    out = []
    for block in text.split('<h4 style=')[1:]:
        vid = re.search(r'fnShowVioltCtnt\(.*?id="(\d+)"', block, re.S)
        firm = re.search(r'<strong>제조/수출회사</strong><span title="([^"]*)"', block)
        rec = {
            "vid": vid.group(1) if vid else "",
            "name_ko": _span(block, "제품한글명"), "name_en": _span(block, "제품영문명"),
            "class": _span(block, "제품구분"), "item": _span(block, "품목명"), "country": _span(block, "제조국가"),
            "firm": html.unescape(firm.group(1)).strip() if firm else "",
            "office": _span(block, "처리기관"), "date": _span(block, "부적합일자"), "expiry": _span(block, "소비기한일자"),
        }
        m = re.search(r'<strong>위반내역[^<]*</strong><span title="([^"]*)"', block)
        rec["violation"] = html.unescape(m.group(1)).strip() if m else ""
        if rec["vid"] and rec["country"] == country:
            out.append(rec)
    if total and len(out) < total:
        raise RuntimeError(f"Korea list returned {len(out)} of {total} rows; page format may have changed")
    return out


def office_zh(s):
    for ko, zh in OFFICE.items():
        s = s.replace(ko, zh)
    return s


def product_text(r):
    return r["name_ko"] + (f"（{r['name_en']}）" if r["name_en"] else "") + (f"；品目：{r['item']}" if r["item"] else "")


def normalize(r, tr):
    machine = bool(tr.get("product") or tr.get("detail"))
    return {
        "id": f"KR-{r['vid']}", "src": "KR", "pub_date": r["date"], "insp_date": None,
        "grp": GROUP.get(r["class"], "食品"), "ind": "", "ntype": None,
        "product": tr.get("product") or r["name_ko"], "product_orig": product_text(r),
        "problems": tr.get("probs") or ["其他"],
        "detail": tr.get("detail") or r["violation"], "legal_limit": "", "quantity": "",
        "firm": r["firm"], "importer": "", "lab_tested": True, "entry_no": "",
        "action": "退回或销毁", "note": ("处理机关：" + office_zh(r["office"])) if r["office"] else "",
        "url": PAGE, "raw": r, "machine_translated": machine,
    }
