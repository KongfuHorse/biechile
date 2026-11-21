"""EU RASFF: food, feed and food contact material notifications with China as country of origin.

Uses the public RASFF Window API (no key). All notification types are kept and labelled:
border rejections and notifications from market controls. RASFF Window does not publish
company names or brands.
"""
import datetime as dt
import re
import time

import requests

API = "https://webgate.ec.europa.eu/rasff-window/backend/public/notification"
VIEW = "https://webgate.ec.europa.eu/rasff-window/screen/notification/{}"
HEAD = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (biechile.com data collector)"}

NTYPE = {
    "border rejection notification": "边境拒绝",
    "alert notification": "预警通报",
    "information notification for attention": "信息通报（关注）",
    "information notification for follow-up": "信息通报（跟进）",
    "news": "新闻通报", "news notification": "新闻通报",
    "non-compliance notification": "不合规通报",
}
BASIS = {
    "border control - consignment detained": "口岸检查，货物扣留",
    "border control - consignment released": "口岸检查，货物已放行",
    "border control - consignment under customs": "口岸检查，海关监管中",
    "official control on the market": "市场官方抽检",
    "company's own check": "企业自检",
    "consumer complaint": "消费者投诉",
    "food poisoning": "食物中毒",
    "monitoring of media": "媒体监测",
    "official control in non-member country": "非成员国官方检查",
    "border control - forwarded to destination": "口岸检查，转运至目的地",
}
ACTION = {
    "re-dispatch": "退回", "destruction": "销毁", "import not authorised": "不准入境",
    "official detention": "官方扣留", "detained by operator": "企业自行扣留",
    "withdrawal from the market": "撤出市场", "recall from consumers": "向消费者召回",
    "recall from consumer": "向消费者召回", "informing recipient(s)": "通知收货方",
    "informing recipients": "通知收货方", "physical/chemical treatment": "理化处理",
    "placed under customs seals": "海关封存", "return to consignor": "退回发货方",
    "no stock left": "已无库存", "product (presumably) no longer on the market": "产品可能已不在市场",
    "public warning - press release": "公开警示", "seizure": "查封", "blocked": "封存",
    "use for other purpose than food/feed": "改作非食用/饲料用途", "withdrawal from recipient(s)": "从收货方撤回",
    "re-dispatch or destruction": "退回或销毁", "destruction of the product": "销毁",
    "use in feed": "改作饲料", "labelling rectified": "更正标签", "no action taken": "未采取措施",
    "seizure of the product": "查封", "monitoring of the recall/withdrawal": "监督召回/撤回",
    "informing consignor": "通知发货方", "informing authorities": "通知主管部门",
    "reinforced checking": "加强检查", "official detention by authorities": "官方扣留",
    "withdrawal from recipients": "从收货方撤回", "recall from recipients": "从收货方召回",
    "re-dispatch to consignor": "退回发货方", "destruction by operator": "企业销毁",
    "information on the website of the company": "企业网站公告",
    "product (to be) redispatched or destroyed": "退回或销毁", "product to be destroyed": "销毁",
    "product to be redispatched": "退回", "relabelling": "重新贴标", "no distribution": "未流通",
    "return to the dispatcher": "退回发货方", "destruction ordered": "责令销毁", "import blocked": "禁止入境",
    "official detention ordered": "责令扣留", "detention by operator": "企业自行扣留",
}
RISK = {"serious": "严重", "potentially serious": "可能严重", "potential risk": "潜在风险", "potential risk": "潜在风险", "not serious": "不严重", "no risk": "无风险",
        "undecided": "未定"}
COUNTRY = {"AT": "奥地利", "BE": "比利时", "BG": "保加利亚", "HR": "克罗地亚", "CY": "塞浦路斯", "CZ": "捷克",
           "DK": "丹麦", "EE": "爱沙尼亚", "FI": "芬兰", "FR": "法国", "DE": "德国", "GR": "希腊", "HU": "匈牙利",
           "IE": "爱尔兰", "IT": "意大利", "LV": "拉脱维亚", "LT": "立陶宛", "LU": "卢森堡", "MT": "马耳他",
           "NL": "荷兰", "PL": "波兰", "PT": "葡萄牙", "RO": "罗马尼亚", "SK": "斯洛伐克", "SI": "斯洛文尼亚",
           "ES": "西班牙", "SE": "瑞典", "NO": "挪威", "IS": "冰岛", "LI": "列支敦士登", "CH": "瑞士",
           "GB": "英国", "XI": "北爱尔兰", "UK": "英国"}


def _date(s):
    return dt.datetime.strptime(s[:10], "%d-%m-%Y").date()


def search(since, until=None, delay=0.3):
    """All notification summaries validated between since and until, origin China only."""
    d0 = dt.date.fromisoformat(since)
    d1 = dt.date.fromisoformat(until) if until else dt.date.today()
    out = []
    while d0 <= d1:  # one month at a time keeps pages small
        end = min(d1, (d0.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1))
        page = 1
        while True:
            body = {"parameters": {"pageNumber": page, "itemsPerPage": 100},
                    "ecValidDateFrom": d0.strftime("%d-%m-%Y 00:00:00"),
                    "ecValidDateTo": end.strftime("%d-%m-%Y 23:59:59")}
            r = requests.post(API + "/search/consolidated/", json=body, headers=HEAD, timeout=90)
            r.raise_for_status()
            data = r.json()
            items = data.get("notifications") or []
            out += [n for n in items if any((c or {}).get("isoCode") == "CN" for c in n.get("originCountries") or [])]
            if page >= (data.get("totalPages") or 1) or not items:
                break
            page += 1
            time.sleep(delay)
        d0 = end + dt.timedelta(days=1)
    return out


def detail(notif_id):
    r = requests.get(f"{API}/view/id/{notif_id}/", headers=HEAD, timeout=90)
    r.raise_for_status()
    return r.json()


def fetch(since, until=None, delay=0.3):
    out = []
    for n in search(since, until):
        try:
            d = detail(n["notifId"])
        except requests.RequestException:
            d = {}
        out.append({"summary": n, "detail": d})
        time.sleep(delay)
    return out


def group(rec):
    s, d = rec["summary"], rec.get("detail") or {}
    ptype = ((d.get("productType") or s.get("productType") or {}).get("description") or "").lower()
    cat = (((d.get("product") or {}).get("productCategory") or s.get("productCategory") or {}).get("description") or "").lower()
    if "contact" in ptype:
        return "食品接触材料"
    if "feed" in ptype:
        return "饲料"
    if "supplement" in cat or "dietetic" in cat:
        return "膳食补充剂"
    return "食品"


def product_text(rec):
    p = ((rec.get("detail") or {}).get("product") or {}).get("description") or ""
    return p.strip()


def subject(rec):
    return (rec["summary"].get("subject") or "").strip()


def _unit(u):
    return re.sub(r"\s*-\s*(ppm|ppb|ppt)$", "", (u or "").strip())


def _findings(d):
    out, limits = [], []
    for f in ((d.get("product") or {}).get("findings") or [])[:6]:
        res = (f.get("analyticalResult") or "").strip()
        unit = _unit(f.get("unit"))
        lim = (f.get("maxPermittedLvl") or "").strip()
        lim = (lim.rsplit(" ", 1)[0] + " " + _unit(lim.rsplit(" ", 1)[1])) if " " in lim else lim
        lim = re.sub(r"\s*-\s*(ppm|ppb|ppt)$", "", lim)
        if res and re.search(r"\d", res):
            out.append(f"{res} {unit}".strip())
        if lim:
            limits.append(lim)
    return out, list(dict.fromkeys(limits))


def _slim(x):
    """Drop the large catalogue objects so raw stays small."""
    if isinstance(x, dict):
        return {k: _slim(v) for k, v in x.items() if not k.endswith("Catalogue") and k != "deserialiseType"}
    if isinstance(x, list):
        return [_slim(i) for i in x]
    return x


def normalize(rec, tr):
    s, d = rec["summary"], rec.get("detail") or {}
    prod = d.get("product") or {}
    results, limits = _findings(d)
    cls = ((d.get("notificationClassification") or s.get("notificationClassification") or {}).get("description") or "").lower()
    basis = ((d.get("notificationBasis") or {}).get("description") or "").strip()
    risk = ((d.get("risk") or {}).get("riskDecision") or (s.get("riskDecision") or {}).get("description") or "").strip()
    notifier = (s.get("notifyingCountry") or {}).get("isoCode") or ""
    by_action = {}
    for m in prod.get("measures") or []:
        a = ((m.get("actionTaken") or {}).get("description") or "").strip()
        if a:
            who = COUNTRY.get(((m.get("takenBy") or {}).get("isoCode") or ""), "")
            lst = by_action.setdefault(ACTION.get(a.lower(), a), [])
            if who and who not in lst:
                lst.append(who)
    measures = [a + (f"（{'、'.join(w)}）" if w else "") for a, w in by_action.items()]
    detail_zh = tr.get("detail") or subject(rec)
    extra = []
    if results:
        extra.append("检出值：" + "、".join(results))
    if risk:
        extra.append("风险评估：" + RISK.get(risk.lower(), risk))
    if basis:
        extra.append("通报依据：" + BASIS.get(basis.lower(), basis))
    if notifier:
        extra.append("通报国：" + COUNTRY.get(notifier, (s.get("notifyingCountry") or {}).get("organizationName", notifier)))
    return {
        "id": f"EU-{s['reference']}", "src": "EU", "pub_date": _date(s["ecValidationDate"]).isoformat(),
        "insp_date": None, "grp": group(rec), "ind": "", "ntype": NTYPE.get(cls, cls or None),
        "product": tr.get("product") or product_text(rec) or subject(rec),
        "product_orig": product_text(rec) or subject(rec),
        "problems": tr.get("probs") or ["其他"],
        "detail": detail_zh, "note": "；".join(extra),
        "legal_limit": "、".join(limits), "quantity": "", "firm": "", "importer": "",
        "lab_tested": bool(results), "entry_no": "", "action": "；".join(dict.fromkeys(measures)),
        "url": VIEW.format(s["notifId"]), "raw": {"summary": s, "detail": _slim({k: d.get(k) for k in
                ("reference", "subject", "notificationClassification", "productType", "notificationBasis",
                 "product", "risk") if k in d})},
        "machine_translated": bool(tr.get("product") or tr.get("detail")),
    }
