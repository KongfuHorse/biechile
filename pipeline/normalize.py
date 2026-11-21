"""Turn raw source rows into one shared record format (Simplified Chinese, shared problem types)."""
import csv
import json
import os
import re

import opencc  # opencc-python-reimplemented

REF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ref")

# ---------------- shared problem types ----------------
# 农药残留 兽药残留 污染物 微生物 色素/添加剂 材质/溶出 卫生/生产 产品标准 标签 手续/审批 其他

FDA_CODE = {  # FDA charge code -> (中文说明, 问题类型)
    "UNSAFE COL": ("含不安全色素", "色素/添加剂"),
    "COLOR LBLG": ("未标注人工色素", "标签"),
    "YELLOW #5": ("含未标注的黄色5号色素", "色素/添加剂"),
    "UNSAFE ADD": ("含不安全食品添加剂", "色素/添加剂"),
    "CYCLAMATE": ("含甜蜜素", "色素/添加剂"),
    "MELAMINE": ("含三聚氰胺", "污染物"),
    "POISONOUS": ("含有毒有害物质", "污染物"),
    "PESTICIDE": ("农药残留", "农药残留"),
    "VETDRUGRES": ("兽药残留", "兽药残留"),
    "LISTERIA": ("李斯特菌", "微生物"),
    "SALMONELLA": ("沙门氏菌", "微生物"),
    "FILTHY": ("含污秽、腐败物", "卫生/生产"),
    "FILTH": ("含污秽物", "卫生/生产"),
    "UNFIT4FOOD": ("不适合食用", "卫生/生产"),
    "INADPRCCTL": ("加工过程控制不足", "卫生/生产"),
    "HELD INSAN": ("在不卫生条件下生产或储存", "卫生/生产"),
    "DRUG GMPS": ("不符合药品GMP", "卫生/生产"),
    "FSVP VIO": ("进口商未履行外国供应商核查(FSVP)", "手续/审批"),
    "NO PROCESS": ("未备案加工工艺", "手续/审批"),
    "NEEDS FCE": ("未注册低酸/酸化罐头企业", "手续/审批"),
    "UNAPPROVED": ("未获批的新药", "手续/审批"),
    "NO 510(K)": ("医疗器械未取得510(k)许可", "手续/审批"),
    "NO PMA": ("医疗器械未获上市前批准", "手续/审批"),
    "NOT LISTED": ("产品未登记列名", "手续/审批"),
    "FRNMFGREG": ("外国生产商未注册", "手续/审批"),
    "REGISTERED": ("经销商未注册", "手续/审批"),
    "TP NO PMTA": ("烟草产品未获上市许可", "手续/审批"),
    "TP NO SE": ("烟草产品无实质等同认定", "手续/审批"),
    "NO REGISTR": ("电子产品未提交报告", "手续/审批"),
    "NEW VET DR": ("未获批兽药", "手续/审批"),
    "DRG REF EI": ("药企拒绝或拖延检查", "手续/审批"),
    "NON STD": ("不符合电子产品性能标准", "产品标准"),
    "NO TAG": ("缺少合格认证标签", "产品标准"),
    "NOT IMPACT": ("眼镜镜片不抗冲击", "产品标准"),
    "COSM COLOR": ("化妆品含违规色素", "色素/添加剂"),
    "LIST INGRE": ("未列出配料", "标签"),
    "LACKS N/C": ("未标净含量", "标签"),
    "NO ENGLISH": ("缺少英文标签", "标签"),
    "NUTRIT LBL": ("缺少营养标签", "标签"),
    "ALLERGEN": ("未标注过敏原", "标签"),
    "INCONSPICU": ("标签信息不醒目", "标签"),
    "USUAL NAME": ("未标通用名称", "标签"),
    "LACKS FIRM": ("未标企业名称地址", "标签"),
    "DIRSEXMPT": ("缺少使用说明", "标签"),
    "CSTIC LBLG": ("化妆品标签不合规", "标签"),
    "COSM MISB2": ("化妆品标签误导", "标签"),
    "FALSE": ("标签虚假或误导", "标签"),
    "DEVICEGMPS": ("医疗器械不符合生产质量规范", "卫生/生产"),
    "DEVGMPS": ("医疗器械不符合生产质量规范", "卫生/生产"),
    "STERILITY": ("无菌状态不符", "卫生/生产"),
    "MFR INSAN": ("在不卫生条件下生产", "卫生/生产"),
    "MFR INJ": ("生产条件可能危害健康", "卫生/生产"),
    "NEEDS ACID": ("酸化食品工艺不合规", "卫生/生产"),
    "HOLES": ("器械有缺陷或破洞", "产品标准"),
    "DV QUALITY": ("器械质量或纯度不符", "产品标准"),
    "FAILS STD": ("不符合器械性能标准", "产品标准"),
    "CHOKE HZRD": ("含异物或有窒息风险", "产品标准"),
    "COSMETFPLA": ("化妆品含未标注色素", "色素/添加剂"),
    "PB-FOOD": ("含铅", "污染物"),
    "807REFUSAL": ("外国工厂拒绝FDA检查", "手续/审批"),
    "REFUSE EI": ("工厂拒绝或拖延FDA检查", "手续/审批"),
    "AF-NONRSP": ("酸化食品企业未回复FDA", "手续/审批"),
    "TP VIOL911": ("烟草产品违规宣称低风险", "手续/审批"),
    "TPNOWRNLBL": ("烟草产品缺少警示标签", "标签"),
    "TPLACKFIRM": ("烟草产品未标企业名称", "标签"),
    "TPFDA4BLBL": ("烟草产品标签不合规", "标签"),
    "LBLG ADVER": ("标签或广告误导", "标签"),
    "DV NAME": ("器械标签缺少名称", "标签"),
    "ADDED BULK": ("掺入物质增重或掩盖劣质", "其他"),
    "TPLKUSSLLB": ("烟草产品未标\"仅限美国销售\"", "标签"),
    "TPLACKSNC": ("烟草产品未标净含量", "标签"),
    "TPNICWARN": ("烟草产品缺少尼古丁警示", "标签"),
    "TPFDA4ALBL": ("烟草产品标签暗示更安全", "标签"),
    "TP FLAVOR": ("烟草产品违反口味标准", "产品标准"),
    "LABELING": ("包装标签不符合规定", "标签"),
    "FLAVR LBLG": ("未标注人工香料", "标签"),
    "PRESRV LBL": ("未标注防腐剂", "标签"),
    "SULFITELBL": ("未标注亚硫酸盐", "标签"),
    "COLORLABEL": ("色素标注不醒目", "标签"),
    "JUICE %": ("未标果汁含量", "标签"),
    "HEALTH C": ("未经批准的营养或健康声称", "标签"),
    "DIETARYLBL": ("膳食补充剂标签不合规", "标签"),
    "DIETARYING": ("膳食补充剂标签不合规", "标签"),
    "PLANT PART": ("膳食补充剂未标植物部位", "标签"),
    "NCONTACT": ("膳食补充剂未标联系方式", "标签"),
    "SBGINSENG": ("冒称人参", "标签"),
    "STD NAME": ("不符合标准名称要求", "标签"),
    "STD IDENT": ("不符合产品标准定义", "标签"),
    "STD QUALIT": ("低于标准质量未标注", "标签"),
    "STD LABEL": ("未按性能标准标注", "标签"),
    "WRONG IDEN": ("以其他食品名义销售", "标签"),
    "IMITATION": ("仿制食品未标注", "标签"),
    "LENS CERT": ("眼镜片抗冲击证明不实", "标签"),
    "FALSEDRUG": ("药品标签虚假或误导", "标签"),
    "DIRECTIONS": ("缺少使用说明", "标签"),
    "DRUG NAME": ("药品未标名称或成分", "标签"),
    "N-RX INACT": ("非处方药未标非活性成分", "标签"),
    "WARNINGS": ("缺少警示说明", "标签"),
    "RXPERSONAL": ("需要处方的器械", "手续/审批"),
    "RX DEVICE": ("处方器械未标处方标识", "标签"),
    "RX LEGEND": ("处方药未标处方标识", "标签"),
    "RXLABEL": ("未标\"Rx Only\"", "标签"),
    "COSMETLBLG": ("化妆品标签不合规", "标签"),
    "COSM MISB": ("化妆品标签误导", "标签"),
    "DANGEROUS": ("按说明使用可能危害健康", "产品标准"),
    "708LISTING": ("药品未登记列名", "手续/审批"),
    "NO PMA/PDP": ("三类器械未获上市批准", "手续/审批"),
    "NO LICENSE": ("未获许可的生物制品或药品", "手续/审批"),
    "NDIDIETSP": ("含未申报的新膳食成分", "手续/审批"),
    "DE IMP GMP": ("医疗器械不符合生产质量规范", "卫生/生产"),
    "SUPPL GMP": ("膳食补充剂不符合生产规范", "卫生/生产"),
    "MFRHACCP": ("生产商未执行HACCP", "卫生/生产"),
    "IMPTRHACCP": ("进口商未执行HACCP", "卫生/生产"),
    "INSANITARY": ("在不卫生条件下生产或储存", "卫生/生产"),
    "COSMETIC": ("化妆品原料在不卫生条件下生产", "卫生/生产"),
    "POSS N/STR": ("可能含污秽、腐败物", "卫生/生产"),
    "FOREIGN OB": ("含异物", "卫生/生产"),
    "DR QUALITY": ("药品质量不符合药典", "产品标准"),
    "POISONORD": ("含有毒有害物质", "污染物"),
    "HISTAMINE": ("组胺超标", "污染物"),
    "NITROFURAN": ("含硝基呋喃", "兽药残留"),
    "POIS CHLOR": ("含氯霉素", "兽药残留"),
    "BACTERIA": ("含致病菌", "微生物"),
    "COL ADDED": ("含不安全色素", "色素/添加剂"),
    "UNSFDIETUS": ("膳食补充剂成分不安全", "污染物"),
    "UNSFDIETLB": ("膳食补充剂成分有重大风险", "污染物"),
}

IND_ZH = {
    "Whole Grains, Milled Grain Products, and Starch": "谷物、淀粉", "Bakery Products, Doughs, Bakery Mixes, and Icings": "烘焙食品",
    "Macaroni and Noodle Products": "面条", "Cereal Preparations, Breakfast Foods": "早餐谷物",
    "Snack Food Items (Flour, Meal, or Vegetable Base)": "休闲零食", "Milk, Butter, and Dried Milk Products": "乳制品",
    "Ice Cream and Related Products": "冰淇淋、冷饮", "Filled Milk and Imitation Milk Products": "仿乳制品",
    "Fishery/Seafood Products": "水产品", "Vegetable Protein Products (Simulated Meats)": "植物蛋白制品",
    "Fruit and Fruit Products": "水果及制品", "Nuts and Edible Seeds": "坚果、籽类",
    "Vegetables and Vegetable Products": "蔬菜及制品", "Spices, Flavors, and Salts": "香辛料、调味",
    "Soft Drinks and Waters": "饮料、饮用水", "Coffee and Tea": "咖啡、茶",
    "Candy without Chocolate, Candy Specialties, and Chewing Gum": "糖果", "Chocolate and Cocoa Products": "巧克力",
    "Gelatin, Rennet, Pudding Mixes, and Pie Fillings": "果冻、布丁", "Food Sweeteners (Nutritive)": "甜味料",
    "Multiple Food Dinners, Gravies, Sauces, and Specialties (Total Diet)": "复合食品、酱料", "Soups": "汤类",
    "Food Additives - for Human Use": "食品添加剂", "Miscellaneous Food Related Items": "其他食品相关",
    "Vitamins, Minerals, Proteins, and Unconventional Dietary Specialties for Humans": "膳食补充剂",
    "Cosmetics": "化妆品", "Human Drugs": "人用药品", "Antibiotics for Human Use": "抗生素",
    "Tobacco Products": "烟草制品", "Light": "照明/激光产品",
    "Anesthesiology Medical Devices": "麻醉器械", "Animal Drugs, Devices, and Diagnostics": "兽药及动物器械",
    "Cardiovascular Medical Devices": "心血管器械", "Chemistry In-Vitro Diagnostic Products": "化学类体外诊断",
    "Dental Medical Devices": "牙科器械", "Ear, Nose, and Throat Medical Devices": "耳鼻喉器械",
    "Gastroenterology and Urology Medical Devices": "消化和泌尿器械", "General Hospital Medical Devices": "通用医院器械",
    "General and Plastic Surgery Medical Devices": "普外和整形器械",
    "Human and Animal Therapeutic Biologic and Biosimilar Drugs": "生物制品和生物类似药",
    "Microbiology In-Vitro Diagnostic Products": "微生物类体外诊断", "Neurology Medical Devices": "神经科器械",
    "Obstetrics and Gynecology Medical Devices": "妇产科器械", "Ophthalmic Medical Devices": "眼科器械",
    "Orthopedics Medical Devices": "骨科器械", "Physical Medicine Medical Devices": "物理治疗器械",
    "Pharmaceutical Necessities and Containers for Drugs and Biologics": "药用辅料和容器",
    "Baby (Infant and Junior) Food Products": "婴幼儿食品", "Beverage Bases": "饮料基料",
    "Cheese and Cheese Products": "奶酪", "Dietary Conventional Foods and Meal Replacements": "膳食食品和代餐",
    "Dressings and Condiments": "调味酱料", "Egg and Egg Products": "蛋及蛋制品",
    "Hematology In-Vitro Diagnostic Products": "血液学体外诊断", "Immunology In-Vitro Diagnostic Products": "免疫学体外诊断",
    "Ionizing": "电离辐射产品", "Non-Medicated Animal Feeds": "动物饲料",
    "Pathology In-vitro Diagnostic Products": "病理体外诊断", "Pet and Laboratory Animal Foods": "宠物食品",
    "Radiology Medical Devices": "放射器械", "Sound": "声学产品",
    "Toxicology In-Vitro Diagnostic Products": "毒理学体外诊断",
}

# Taiwan term -> mainland term (pesticide and drug names use mainland common names)
TW_TERMS = [
    ("硝基砆喃", "硝基呋喃"), ("对羟苯甲酸", "对羟基苯甲酸"), ("苏丹色素三号", "苏丹红III"),
    ("戴奥辛", "二噁英"), ("萤光增白剂", "荧光增白剂"), ("动物用药", "兽药"), ("残留农药", "农药残留"),
    ("恩氟喹啉羧酸", "恩诺沙星"), ("待克利", "苯醚甲环唑"), ("三氟敏", "肟菌酯"), ("克安勃", "氯虫苯甲酰胺"),
    ("氟派瑞", "氟吡菌酰胺"), ("百利普芬", "吡丙醚"), ("赛速安", "噻虫嗪"), ("禄芬隆", "虱螨脲"),
    ("三赛唑", "三环唑"), ("芬普尼", "氟虫腈"), ("可尼丁", "噻虫胺"), ("草脱净", "莠去津"),
    ("氟尼胺", "氟啶虫酰胺"), ("扶吉胺", "氟啶胺"), ("普拔克", "霜霉威"), ("赛灭宁", "氯氰菊酯"),
    ("巴克素", "多效唑"), ("克美素", "矮壮素"), ("益达胺", "吡虫啉"), ("灭芬诺", "苯菌酮"),
    ("殴螨多", "炔螨特"), ("欧螨多", "炔螨特"), ("百克敏", "吡唑醚菌酯"), ("克凡派", "虫螨腈"),
    ("陶斯松", "毒死蜱"), ("三落松", "三唑磷"),
    ("美耐皿", "密胺"), ("优格机", "酸奶机"), ("奇异果", "猕猴桃"),
    ("案内不符合商品", "该批不合格产品"), ("案内产品", "该批产品"),
    ("业者提具说明", "企业提交说明"), ("业者", "企业"),
]

_cc = opencc.OpenCC("tw2sp")
_fda_product_zh = json.load(open(os.path.join(REF, "fda_product_zh.json"), encoding="utf-8"))
_charges = {c["ASC_ID"].strip(): c for c in csv.DictReader(open(os.path.join(REF, "fda_charges.csv"), encoding="utf-8-sig"))}

# collected during a run so new terms can be reviewed by hand (or machine translated)
untranslated = {"fda_product": set(), "fda_industry": set(), "fda_code": set()}

# machine translations loaded from the term_translations table: {kind: {source: zh}}
MT = {"fda_product": {}, "fda_industry": {}, "fda_code": {}}

# code -> English charge statement, used when asking for a machine translation
CODE_TEXT = {c["CHRG_CODE"].strip(): (c["CHRG_STMNT_TEXT"] or "").strip() for c in _charges.values()}


def tw_zh(text):
    """Traditional -> Simplified, then TW terms -> mainland terms. Text inside 「」 (law names) keeps its wording."""
    parts = re.split(r"(「[^」]*」)", _cc.convert(text or ""))
    out = []
    for p in parts:
        if not p.startswith("「"):
            for a, b in TW_TERMS:
                p = p.replace(a, b)
        out.append(p)
    return "".join(out)


def tw_problems(cat, finding):
    t = (cat or "") + (finding or "")
    out = []
    if "容器具" in t or "螢光增白劑" in t: out.append("材质/溶出")
    if "農藥" in t: out.append("农药残留")
    if "動物用藥" in t: out.append("兽药残留")
    if any(k in t for k in ["戴奧辛", "重金屬", "污染物", "毒素"]): out.append("污染物")
    if any(k in t for k in ["防腐劑", "漂白劑", "著色劑", "甜味劑", "添加物", "二氧化硫"]): out.append("色素/添加剂")
    if any(k in t for k in ["菌", "微生物"]): out.append("微生物")
    if "標示" in t: out.append("标签")
    return out or ["其他"]


def normalize_tw(r):
    """r: dict from scrapers.tw.parse()"""
    probs = tw_problems(r.get("category"), r.get("finding"))
    return {
        "id": f"TW-{r['id']}", "src": "TW",
        "pub_date": r["publish_date"], "insp_date": r.get("inspection_date") or None,
        "grp": "食品接触材料" if "材质/溶出" in probs else "食品", "ind": "",
        "product": tw_zh(r.get("product")), "product_orig": r.get("product"),
        "problems": probs, "detail": tw_zh(r.get("finding")), "legal_limit": tw_zh(r.get("legal_limit")),
        "quantity": tw_zh(r.get("quantity")), "firm": tw_zh(r.get("manufacturer")),
        "importer": tw_zh(re.sub(r"^\d+\s*", "", r.get("importer") or "")),
        "lab_tested": True, "entry_no": "", "action": tw_zh(r.get("action")), "url": r["url"], "raw": r,
        "machine_translated": False,
    }


def fda_group(pc):
    n = int(pc[:2])
    if n == 54: return "膳食补充剂"
    if 2 <= n <= 52: return "食品"
    if n == 53: return "化妆品"
    if 55 <= n <= 66: return "药品"
    if 67 <= n <= 72: return "兽药/动物用品"
    if 73 <= n <= 92: return "医疗器械"
    if 94 <= n <= 97: return "电子辐射产品"
    if n == 98: return "烟草"
    return "其他"


def normalize_fda(r):
    """r: one row from the FDA import_refusals API"""
    reasons, probs, machine = [], [], False
    for i in [x.strip() for x in (r.get("RefusalCharges") or "").split(",") if x.strip()]:
        c = _charges.get(i)
        if not c:
            reasons.append(f"代码{i}（FDA代码表未收录）"); probs.append("其他"); continue
        code = c["CHRG_CODE"].strip()
        if code in FDA_CODE:
            zh, pr = FDA_CODE[code]
        else:
            pr = "标签" if "MISBRAND" in (c["SCTN_NAME"] or "").upper() else "其他"
            if code in MT["fda_code"]:
                zh = MT["fda_code"][code]; machine = True
            else:
                untranslated["fda_code"].add(code); zh = code
        reasons.append(f"{zh} [{code}]"); probs.append(pr)
    pdesc = (r.get("ProductCodeDescription") or "").strip()
    if pdesc in _fda_product_zh:
        product = _fda_product_zh[pdesc]
    elif pdesc in MT["fda_product"]:
        product = MT["fda_product"][pdesc]; machine = True
    else:
        untranslated["fda_product"].add(pdesc); product = pdesc
    ind = r.get("IndustryCodeDescription") or ""
    if ind in IND_ZH:
        ind_zh = IND_ZH[ind]
    elif ind in MT["fda_industry"]:
        ind_zh = MT["fda_industry"][ind]; machine = True
    else:
        untranslated["fda_industry"].add(ind); ind_zh = ind
    grp = fda_group(r["ProductCode"])
    if grp == "食品" and ("(FOODWARE, COOKWARE & TABLEWARE)" in pdesc or pdesc.startswith("BOTTLES AND JARS")):
        grp = "食品接触材料"  # tableware and containers, same group as Taiwan's 容器具
    yes = lambda v: (v or "").strip() == "Yes"
    return {
        "id": f"US-{r['ShipmentID']}-{r['RefusalDate']}", "src": "US",
        "pub_date": r["RefusalDate"], "insp_date": None,
        "grp": grp, "ind": ind_zh,
        "product": product, "product_orig": pdesc, "machine_translated": machine,
        "problems": sorted(set(probs)) or ["其他"], "detail": "；".join(reasons),
        "legal_limit": "", "quantity": "", "firm": (r.get("FirmName") or "").strip(), "importer": "",
        "lab_tested": yes(r.get("FDASampleAnalysis")) or yes(r.get("PrivateLabAnalysis")),
        "entry_no": (r.get("ShipmentID") or "").split("/")[0], "action": "拒绝入境",
        "url": r.get("FirmProfile") or "", "raw": r,
    }
