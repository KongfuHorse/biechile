"""US Consumer Product Safety Commission (CPSC): recalls of consumer products made in China.

Public REST API, no key. Each recall has the country of manufacture, product photos (public CPSC
addresses, shown directly), manufacturer, importer, retailers, units sold, injuries and remedy.
"""
import datetime as dt
import re

import requests

API = "https://www.saferproducts.gov/RestWebServices/Recall"
UA = {"User-Agent": "Mozilla/5.0 (biechile.com data collector)"}

GROUPS = [  # first match wins; checked against the product name (title only when the name is missing)
    (r"\btoys?\b|puzzle|doll|plush|slime|building block|surprise egg|magnetic (balls?|cubes?|tiles?)|rattle|teether|water balloon|crayola|fidget", "玩具"),
    (r"crib|bassinet|stroller|high chair|\bbaby|infant|toddler|children'?s|\bkids?'?\b|pacifier|soother|play ?yard|bouncer|walker|car seat|bath seat|safety gates?|learning tower|lounger", "儿童用品"),
    (r"e-?bikes?|scooter|hoverboard|bicycle|helmet|skateboard|trampoline|\bpool|kayak|fitness|treadmill|exercise|rowing|\batvs?\b|"
     r"camping|carabiner|sauna|equine|tent\b|trikes?\b", "运动休闲用品"),
    (r"charger|power bank|power station|batter(y|ies)|heater|\bfans?\b|fridge|refrigerator|freezer|cooker|fryer|blender|kettle|"
     r"extension cord|power strip|outlet|adapter|dehumidifier|humidifier|vacuum|\birons?\b|hair dryer|toaster|microwave|oven|"
     r"steamer|diffuser|electric|heating pad|projector|speaker|headphone|smartwatch|earbuds?", "电器"),
    (r"\blamps?\b|\blights?\b|lantern|\bled\b|chandelier|sconce", "灯具灯串"),
    (r"dresser|\bchests?\b|cabinet|bookcase|shel(f|ves|ving)|\bdesks?\b|\btables?\b|\bchairs?\b|stool|\bbeds?\b|bunk|mattress|sofa|wardrobe|furniture|"
     r"tip restraint|anti-tip", "家具"),
    (r"hoodie|jacket|pajama|nightgown|sleepwear|robe|costume|garment|clothing|sweatshirt|shirt|\bdress(es)?\b|drawstring|shoe|boot", "服装纺织"),
    (r"lighter|candle|firework|torch", "打火机"),
    (r"cookware|\bpans?\b|\bpots?\b|knife|knives|\bmugs?\b|\bcups?\b|bottle|kitchen|utensil|grill|smoker|garlic press|ice crusher|cotton candy", "厨房用品"),
    (r"necklace|bracelet|earring|jewel", "首饰配饰"),
    (r"\bsaws?\b|drill|ladder|\btools?\b|generator|pressure washer|mower|trimmer|chainsaw|grease gun|scaffold|ramps?\b|handrail|caster", "机械工具"),
    (r"cosmetic|nail polish|lotion|shampoo|\boil\b", "化妆品"),
]
REMEDY = {"refund": "退款", "replace": "更换", "repair": "维修", "label": "加贴标签", "dispose": "销毁"}


def fetch(since, until=None):
    """Recalls with China as a country of manufacture, published between the dates."""
    out, d0 = [], dt.date.fromisoformat(since)
    d1 = dt.date.fromisoformat(until) if until else dt.date.today()
    while d0 <= d1:  # one year per request keeps responses small
        end = min(d1, dt.date(d0.year, 12, 31))
        r = requests.get(API, params={"format": "json", "RecallDateStart": d0.isoformat(), "RecallDateEnd": end.isoformat()},
                         headers=UA, timeout=180)
        r.raise_for_status()
        out += [x for x in r.json() if any((m or {}).get("Country") == "China" for m in x.get("ManufacturerCountries") or [])]
        d0 = end + dt.timedelta(days=1)
    return out


def _names(lst, key="Name"):
    return [re.sub(r"\s+", " ", (x or {}).get(key) or "").strip() for x in lst or [] if (x or {}).get(key)]


def product_text(r):
    return "; ".join(_names(r.get("Products"))) or r.get("Title") or ""


def detail_text(r):
    parts = _names(r.get("Hazards"))
    inj = _names(r.get("Injuries"))
    if inj:
        parts.append("Incidents/Injuries: " + " ".join(inj))
    sold = _names(r.get("Retailers"))
    if sold:
        parts.append("Sold at: " + " ".join(sold))
    return "\n".join(parts)


def group(r):
    text = (product_text(r) or r.get("Title") or "").lower()
    for pat, g in GROUPS:
        if re.search(pat, text):
            return g
    return "其他非食品"


def _clean_firm(s):
    return re.sub(r",\s*of\s+.*$", "", s).strip()


def normalize(r, tr):
    units = [p.get("NumberOfUnits") for p in r.get("Products") or [] if p.get("NumberOfUnits")]
    models = [p.get("Model") for p in r.get("Products") or [] if p.get("Model")]
    upcs = _names(r.get("ProductUPCs"), "UPC")
    facts = []
    if models:
        facts.append("型号：" + "、".join(models)[:200])
    if upcs:
        facts.append("条码：" + "、".join(upcs)[:200])
    if units:
        facts.append("数量：" + "；".join(units).replace("About ", "约 ").replace("about ", "约 "))
    remedies = []
    for o in _names(r.get("RemedyOptions"), "Option"):
        z = REMEDY.get(o.lower())
        if z and z not in remedies:
            remedies.append(z)
    makers = [_clean_firm(x) for x in _names(r.get("Manufacturers"))]
    importers = [_clean_firm(x) for x in _names(r.get("Importers")) + _names(r.get("Distributors"))]
    return {
        "id": f"CPSC-{r.get('RecallNumber') or r.get('RecallID')}", "src": "CPSC",
        "pub_date": (r.get("RecallDate") or "")[:10], "insp_date": None, "grp": group(r), "ind": "",
        "ntype": "召回", "product": tr.get("product") or product_text(r), "product_orig": product_text(r),
        "problems": tr.get("probs") or ["其他"], "detail": tr.get("detail") or detail_text(r), "legal_limit": "",
        "quantity": "", "firm": "；".join(dict.fromkeys(makers)), "importer": "；".join(dict.fromkeys(importers)),
        "lab_tested": False, "entry_no": "", "action": "召回" + (f"（{'、'.join(remedies)}）" if remedies else ""),
        "note": "；".join(facts), "url": r.get("URL") or "",
        "raw": {**r, "_detail_src": detail_text(r)}, "machine_translated": bool(tr.get("product") or tr.get("detail")),
    }
