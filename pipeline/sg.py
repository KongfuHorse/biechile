"""EU Safety Gate: alerts on dangerous non-food products, country of origin China.

Uses the official weekly report XML (one file per week, every Friday). Each alert has brand,
product name, model, barcode, the online marketplace if sold online, risk type, measures and
photos. Photos stay on the European Commission server (stable public URLs), so we store only
their ids.
"""
import datetime as dt
import html
import re
import time

import requests

BASE = "https://ec.europa.eu/safety-gate-alerts"
LIST = BASE + "/api/download/weeklyReport/list/xml/en"
IMG = BASE + "/public/api/notification/image/{}"
THUMB = BASE + "/public/api/notification/thumbnail/{}"
UA = {"User-Agent": "Mozilla/5.0 (biechile.com data collector)"}
ORIGIN = "People's Republic of China"

CATEGORY = {
    "Toys": "玩具", "Electrical appliances and equipment": "电器", "Lighting chains": "灯具灯串",
    "Lighting equipment": "灯具灯串", "Protective equipment": "防护用品", "Machinery": "机械工具",
    "Childcare articles and children's equipment": "儿童用品", "Jewellery": "首饰配饰",
    "Clothing, textiles and fashion items": "服装纺织", "Hobby/sports equipment": "运动休闲用品",
    "Chemical products": "化学品", "Decorative articles": "装饰品", "Pyrotechnic articles": "烟花爆竹",
    "Furniture": "家具", "Lighters": "打火机", "Cosmetics": "化妆品", "Kitchen/cooking accessories": "厨房用品",
    "Gadgets": "小商品", "Motor vehicles": "机动车及配件", "Explosive atmospheres equipment": "机械工具",
    "Laser pointers": "激光笔", "Communication and media equipment": "通讯电子", "Stationery": "文具",
    "Hand tools": "机械工具", "Construction products": "建材", "Recreational crafts": "运动休闲用品",
    "Food-imitating products": "仿食品产品", "Measuring instruments": "机械工具", "Pressure equipment/vessels": "机械工具",
    "Gas appliances and components": "燃气器具", "Personal protective equipment": "防护用品",
}
RISK = {
    "chemical": "化学有害物", "choking": "窒息/勒颈", "suffocation": "窒息/勒颈", "asphyxiation": "窒息/勒颈",
    "strangulation": "窒息/勒颈", "electric shock": "触电", "fire": "火灾/烧伤", "burns": "火灾/烧伤",
    "injuries": "受伤", "cuts": "受伤", "entrapment": "受伤", "drowning": "溺水", "environment": "环境危害",
    "damage to sight": "视力/听力损伤", "damage to hearing": "视力/听力损伤", "microbiological": "微生物",
    "health risk / other": "其他", "security": "其他", "energy consumption": "其他",
}
LEVEL = {"serious risk": "严重风险", "other risk levels": "其他风险等级", "other types of alerts": "其他类型通报"}
MEASURE = {
    "withdrawal of the product from the market": "撤出市场", "recall of the product from end users": "向消费者召回",
    "removal of this product listing by the online marketplace": "电商平台下架",
    "warning consumers of the risks": "向消费者发出警告", "import rejected at border": "边境拒绝进口",
    "ban on the marketing of the product and any accompanying measures": "禁止销售",
    "destruction of the product": "销毁", "stop of sales": "停止销售",
    "warn the sellers that the product is dangerous.": "警告销售商", "warning the seller of the risks": "警告销售商",
    "marketing subject to prior conditions": "附条件销售", "modification of the user manual": "修改说明书",
    "marking the product with appropriate warnings": "加贴警示标签",
}
COUNTRY = {"Austria": "奥地利", "Belgium": "比利时", "Bulgaria": "保加利亚", "Croatia": "克罗地亚", "Cyprus": "塞浦路斯",
           "Czechia": "捷克", "Czech Republic": "捷克", "Denmark": "丹麦", "Estonia": "爱沙尼亚", "Finland": "芬兰",
           "France": "法国", "Germany": "德国", "Greece": "希腊", "Hungary": "匈牙利", "Ireland": "爱尔兰",
           "Italy": "意大利", "Latvia": "拉脱维亚", "Lithuania": "立陶宛", "Luxembourg": "卢森堡", "Malta": "马耳他",
           "Netherlands": "荷兰", "Poland": "波兰", "Portugal": "葡萄牙", "Romania": "罗马尼亚", "Slovakia": "斯洛伐克",
           "Slovenia": "斯洛文尼亚", "Spain": "西班牙", "Sweden": "瑞典", "Norway": "挪威", "Iceland": "冰岛",
           "Liechtenstein": "列支敦士登", "United Kingdom (Northern Ireland)": "英国（北爱尔兰）"}

S = requests.Session()
S.headers.update(UA)


def _get(url):
    for attempt in range(3):
        try:
            r = S.get(url, timeout=90)
            r.raise_for_status()
            r.encoding = "utf-8"
            return r.text
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))


def _f(block, tag):
    m = re.search(rf"<{tag}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", block, re.S)
    return html.unescape(m.group(1)).strip() if m else ""


def reports(since):
    """Weekly reports published on or after since, oldest first: [(reference, date, url)]."""
    t = _get(LIST)
    d0 = dt.date.fromisoformat(since)
    out = []
    for blk in re.findall(r"<weeklyReport>(.*?)</weeklyReport>", t, re.S):
        d = dt.datetime.strptime(_f(blk, "publicationDate"), "%d/%m/%Y").date()
        if d >= d0:
            out.append((_f(blk, "reference"), d, html.unescape(_f(blk, "URL"))))
    return sorted(out, key=lambda x: x[1])


def parse_report(xml):
    out = []
    for n in re.findall(r"<notifications\b.*?</notifications>", xml, re.S):
        if _f(n, "countryOfOrigin") != ORIGIN:
            continue
        rec = {k: _f(n, k) for k in ("caseNumber", "publicationDate", "reference", "category", "product", "brand",
                                     "name", "type_numberOfModel", "batchNumber", "barcode", "riskType", "danger",
                                     "measures", "URLrecall", "description", "notifyingCountry", "countryOfOrigin",
                                     "type", "level", "onlineTrader", "companyRecallCode", "productionDates")}
        rec["pictures"] = [re.sub(r"\D", "", p.split("/")[-1]) for p in
                           re.findall(r"<picture>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</picture>", n, re.S)]
        if rec["caseNumber"]:
            out.append(rec)
    return out


def fetch_reports(since):
    """Yield (report_reference, [records]) one week at a time."""
    for ref, d, url in reports(since):
        yield ref, parse_report(_get(url))


def rec_id(r):
    return "SG-" + re.sub(r"[^A-Za-z0-9]+", "-", r["caseNumber"]).strip("-")


def product_text(r):
    return " | ".join(x for x in (r["product"], r["name"]) if x)


def detail_text(r):
    d = r["danger"]
    if r["description"]:
        d += "\nDescription: " + r["description"]
    return d


def group(r):
    c = r["category"]
    if c in CATEGORY:
        return CATEGORY[c]
    if c.startswith("Other - "):
        for k, v in CATEGORY.items():
            if k.lower() in c.lower():
                return v
    return "其他非食品"


def problems(r):
    out = []
    for x in re.split(r"[,;]", r["riskType"]):
        p = RISK.get(x.strip().lower())
        if x.strip() and (p or "其他") not in out:
            out.append(p or "其他")
    return out or ["其他"]


def measures(r):
    out = []
    for m in re.findall(r"Category of measure\(s\):\s*(.*?)(?=Date of entry into force|Type of economic|$)",
                        r["measures"], re.S):
        m = m.strip()
        z = MEASURE.get(m.lower(), m)
        if z and z not in out:
            out.append(z)
    return "、".join(out)


def trader(r):
    """'AliExpress(1005008934565892) / ' -> 'AliExpress（商品号 1005008934565892）'"""
    out = []
    for part in r["onlineTrader"].split("/"):
        part = part.strip()
        m = re.match(r"(.*?)\((.*)\)$", part)
        if m:
            name, item = m.group(1).strip(), m.group(2).strip()
            if name.lower() == "other":
                name, item = item, ""
            part = name + (f"（商品号 {item}）" if item else "")
        if part:
            out.append(part)
    return "；".join(out)


def normalize(r, tr):
    facts = []
    if r["type_numberOfModel"]:
        facts.append("型号：" + r["type_numberOfModel"].replace("|", "、"))
    if r["barcode"]:
        facts.append("条码：" + r["barcode"])
    if r["batchNumber"]:
        facts.append("批号：" + r["batchNumber"])
    t = trader(r)
    if t:
        facts.append("销售平台：" + t)
    if r["notifyingCountry"]:
        facts.append("通报国：" + COUNTRY.get(r["notifyingCountry"], r["notifyingCountry"]))
    if r["type"] == "Professional":
        facts.append("专业用途产品")
    return {
        "id": rec_id(r), "src": "SG",
        "pub_date": dt.datetime.strptime(r["publicationDate"], "%d-%m-%Y").date().isoformat(),
        "insp_date": None, "grp": group(r), "ind": "", "ntype": LEVEL.get(r["level"].lower(), r["level"]),
        "product": tr.get("product") or product_text(r), "product_orig": product_text(r),
        "problems": problems(r), "detail": tr.get("detail") or detail_text(r), "legal_limit": "",
        "quantity": "", "firm": r["brand"] if r["brand"].lower() not in ("unknown", "no brand", "none", "-") else "",
        "importer": "", "lab_tested": bool(re.search(r"measured|test|analys", r["danger"], re.I)),
        "entry_no": "", "action": measures(r), "note": "；".join(facts), "url": r["reference"],
        "raw": r, "machine_translated": bool(tr.get("product") or tr.get("detail")),
    }
