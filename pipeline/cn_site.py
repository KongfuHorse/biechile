"""Mainland food sampling results (cn_checks) as website rows, source "CN".

Only failed samples are shown. Problem types are set by fixed rules (no AI).
When the labelled company's objection was upheld (the product was not theirs), the company
name is left out of the row so it is not counted against them.
"""
import hashlib
import os
import re

from . import db


def _glossary(section):
    path = os.path.join(os.path.dirname(__file__), "..", "ref", "glossary.tsv")
    out, cur = [], None
    for line in open(path, encoding="utf-8"):
        if line.startswith("# "):
            cur = line[2:].strip()
            continue
        parts = line.rstrip("\n").split("\t")
        if cur and cur.startswith(section) and len(parts) == 3:
            out.append(re.sub(r"[（(].*", "", parts[2]))
    return out


PESTICIDE = re.compile("|".join(map(re.escape, _glossary("Pesticides"))) +
                       r"|农药|菊酯|有机磷|灭蝇胺|甲胺磷|噻虫|乙酰甲胺磷|敌敌畏|水胺硫磷|三唑磷|倍硫磷|甲拌磷|氟虫腈|啶虫脒|丙溴磷|腈苯唑|嘧霉胺|氯唑磷|久效磷|克百威|涕灭威")
VETDRUG = re.compile("|".join(map(re.escape, _glossary("Veterinary"))) +
                     r"|沙星|磺胺|呋喃|地西泮|甲硝唑|地美硝唑|五氯酚酸钠|氯霉素|孔雀石绿|恩诺|培氟|土霉素|四环素|金霉素|多西环素|甲氧苄啶|克伦特罗|莱克多巴胺|沙丁胺醇|喹乙醇|氟苯尼考|替米考星|尼卡巴嗪|二甲硝咪唑|洛硝哒唑|氯丙嗪|镇静")
MICROBE = re.compile(r"菌|霉菌|酵母|沙门|李斯特|诺如|副溶血|金黄色葡萄球|蜡样芽孢|单核细胞|阪崎|致泻|大肠埃希|商业无菌|病毒")
CONTAM = re.compile(r"铅|镉|铬|汞|砷|镍|锡|黄曲霉|赭曲霉|呕吐毒素|脱氧雪腐|玉米赤霉烯酮|展青霉素|苯并|多环芳烃|亚硝酸盐|硝酸盐|溴酸盐|氯丙醇|缩水甘油|N-二甲基亚硝胺|丙烯酰胺|组胺|挥发性盐基氮|三氯甲烷|余氯|耗氧量|浑浊度|放射性")
ADDITIVE = re.compile(r"甜蜜素|环己基氨基磺酸|糖精|安赛蜜|阿斯巴甜|三氯蔗糖|苯甲酸|山梨酸|脱氢乙酸|丙酸|纳他霉素|二氧化硫|亚硫酸|柠檬黄|日落黄|亮蓝|胭脂红|苋菜红|诱惑红|赤藓红|靛蓝|新红|酸性红|着色剂|色素|铝的残留量|铝（|硼砂|硼酸|过氧化苯甲酰|特丁基对苯二酚|TBHQ|BHA|BHT|没食子酸|乙二胺四乙酸|防腐剂|甜味剂|乙基麦芽酚|双乙酸钠|对羟基苯甲酸|山梨糖醇|乳酸链球菌素|磷酸盐|亚铁氰化钾|溴酸钾|滑石粉|硫酸铝钾")
ILLEGAL = re.compile(r"西地那非|那非|拉非|他达|伐地|酚酞|西布曲明|罗格列酮|格列|二甲双胍|苯乙双胍|地塞米松|泼尼松|氢化可的松|美罗|麻黄碱|育亨宾|吗啡|罂粟碱|可待因|那可丁|苏丹红|罗丹明|碱性橙|吊白块|甲醛|硫氰酸钠|三聚氰胺|非食用|酚丁|酚汀|比沙可啶|双己酚丁|布噻嗪")
LABEL = re.compile(r"标签|标示值|标签标示")
MATERIAL = re.compile(r"迁移|溶出|蒸发残渣|高锰酸钾消耗量|脱色试验|游离性余氯")


def problem_types(text, standard):
    t = text or ""
    out = []
    for name, rx in (("农药残留", PESTICIDE), ("兽药残留", VETDRUG), ("微生物", MICROBE), ("污染物", CONTAM),
                     ("色素/添加剂", ADDITIVE), ("非法添加", ILLEGAL), ("材质/溶出", MATERIAL)):
        if rx.search(t):
            out.append(name)
    if not out:
        out.append("标签" if LABEL.search(t) and not (standard or "") else "产品标准")
    return out


UPHELD = re.compile(r"(?<!不予)认可其?提出的?异议|异议予以认可|不是.{0,60}?(生产|进口|经销|出品|分装)的|没有进口过|停止经营|自行(包装|分装|制作)|假冒|冒用")
NOT_UPHELD = re.compile(r"不予认可|维持初检结论|未予认可")
TAIL = re.compile(r"对抽检中发现的不合格产品.*$|市场监管总局已责成.*$")


def _clean(s):
    return TAIL.sub("", s or "").strip() or None


def rows():
    cols = ("id,notice_url,notice_date,item_no,maker,maker_role,product,problem,test_value,standard_value,"
            "seller,platform,origin,spec,brand,prod_date,category,sample_no,disputed,dispute_note,raw,source")
    out = []
    for c in db.fetch_table("cn_checks", cols, "&passed=is.false&order=id"):
        note = _clean(c.get("dispute_note"))
        disputed = bool(c.get("disputed") and note)
        upheld = disputed and bool(UPHELD.search(note)) and not NOT_UPHELD.search(note)
        maker = (c.get("maker") or "").strip("，；、 ")
        prob = c.get("problem") or ""
        x = prob or "不合格"
        if c.get("test_value"):
            x += "，检验值 " + c["test_value"]
        # other labelled firms (委托方, 进口, 经销...) besides the maker
        others = []
        for part in (c.get("maker_role") or "").split("；"):
            if ":" in part:
                role, name = part.split(":", 1)
                if name and name != maker and role not in ("生产",):
                    others.append(f"{role}：{name}")
        bits = []
        if others and not upheld:
            bits.append("；".join(others))
        if c.get("seller"):
            bits.append("被抽样单位：" + c["seller"] + (f"（{c['platform']}）" if c.get("platform") else ""))
        for k, label in (("brand", "商标"), ("spec", "规格"), ("prod_date", "生产日期"), ("origin", "标称原产地")):
            if c.get(k):
                bits.append(f"{label}：{c[k]}")
        nt = ""
        if upheld:
            bits.append("标签上的企业信息经核实不实，不列企业名。核实结果：" + note)
            maker, nt = "", "标称企业异议成立"
        elif disputed:
            bits.append(note)
            nt = "有异议，未获认可" if NOT_UPHELD.search(note) else "有异议"
            bits[-1] = "异议情况：" + bits[-1]
        key = c.get("sample_no") or f"{c['notice_url']}#{c['item_no']}"
        out.append({
            "id": "CN-" + hashlib.sha1(key.encode()).hexdigest()[:14],
            "src": "CN", "pub_date": c["notice_date"], "grp": "食品", "ind": c.get("category") or "",
            "product": c.get("product") or "", "product_orig": "", "problems": problem_types(prob, c.get("standard_value")),
            "detail": x, "legal_limit": c.get("standard_value") or "", "quantity": "", "firm": maker,
            "importer": "", "lab_tested": True, "entry_no": "", "action": "监督抽检不合格", "url": c["notice_url"],
            "machine_translated": False, "ntype": nt, "note": "；".join(bits)[:800],
        })
    return out
