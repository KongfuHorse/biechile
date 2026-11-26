"""Mainland sampling results (cn_checks) as website rows: source "CN" (SAMR) and "SZ" (Shenzhen).

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
                       r"|农药|除害剂|(?<!硝)唑|菌酯|虫胺|虫嗪|虫腈|虫脲|虫酰肼|螨|硫磷|甲磷|乐果|多菌灵|百菌清|啶|吡虫|噻|毒死蜱|腐霉利|甲霜灵|嘧|哒|氯氰|溴氰|联苯|草甘膦|敌百虫|阿维菌素|甲维盐|菊酯|有机磷|灭蝇胺|甲胺磷|噻虫|乙酰甲胺磷|敌敌畏|水胺硫磷|三唑磷|倍硫磷|甲拌磷|氟虫腈|啶虫脒|丙溴磷|腈苯唑|嘧霉胺|氯唑磷|久效磷|克百威|涕灭威")
VETDRUG = re.compile("|".join(map(re.escape, _glossary("Veterinary"))) +
                     r"|沙星|磺胺|强力霉素|霉素(?!.*酵母)|硝唑|呋喃|地西泮|甲硝唑|地美硝唑|五氯酚酸钠|氯霉素|孔雀石绿|恩诺|培氟|土霉素|四环素|金霉素|多西环素|甲氧苄啶|克伦特罗|莱克多巴胺|沙丁胺醇|喹乙醇|氟苯尼考|替米考星|尼卡巴嗪|二甲硝咪唑|洛硝哒唑|氯丙嗪|镇静")
MICROBE = re.compile(r"细菌|菌落|菌群|菌数|致病菌|杆菌|球菌|弧菌|无菌|霉菌|酵母|沙门|李斯特|诺如|副溶血|金黄色葡萄球|蜡样芽孢|单核细胞|阪崎|致泻|大肠埃希|商业无菌|病毒")
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


NF_RULES = [
    ("触电", r"电气间隙|爬电距离|抗电强度|电气强度|接地|泄漏电流|防触电|触及带电|绝缘|电能量源的防护|电容器的放电|插头|插套|直接插入电网|导体的固定|输入试验|电源线"),
    ("火灾/烧伤", r"发热|温升|热灼伤|短路|热滥用|过充|燃烧|阻燃|着火|灼热丝|耐热|耐燃|非正常工作|异常工作|过载|热塑性零部件|针焰|易燃|闪点"),
    ("窒息/勒颈", r"小零件|绳带|绳索|功能性绳|窒息|包装袋|塑料袋"),
    ("化学有害物", r"甲醛|邻苯|增塑剂|重金属|可迁移元素|偶氮|pH|多环芳烃|致癌|TVOC|苯|有害物质|铅|镉|汞|铬|砷|游离|挥发性有机|VOC|硫含量|有害"),
    ("受伤", r"锐利|尖端|稳定性|强度|跌落|冲击|结构|夹|磁体|磁通|纽扣电池|制动|刹车|耐久|可触及|边缘|断裂|拉力|撕裂|爆破|压力"),
    ("视力/听力损伤", r"声压|蓝光|激光|光生物|视|透光|折射|顶焦度"),
    ("标签", r"标识|标签|标志|使用说明|警示|说明书|铭牌"),
]
NF_GROUPS = [
    (r"玩具|积木|拼图|童车|滑板车|学生用品|文具|笔|书包", "玩具"),
    (r"儿童|婴|童鞋|童装|奶瓶|约束系统|安全座椅|双层床|校服", "儿童用品"),
    (r"移动电源|充电|电源适配器|电池|电热|电器|电饭|电压力锅|电磁灶|热水器|空调|空气调节器|冰箱|吸油烟机|风扇|洗碗机|加热器|电话|服务器|无人机|护理器具|个护|家电|电气产品|防爆电气|坐便器|洗衣机|吹风|电吹|电动|吸尘|加湿|电暖|取暖|插座|开关|延长线|转换器|电线|电缆|按摩|美容仪|电熨斗|微波|烤箱|净化器|消毒柜|电视|音箱|耳机|摄像头|显示器|电脑|计算机|笔记本|平板|手机|移动用户终端|路由器|机顶盒|投影|扫描|打印|办公设备|行车记录|信息技术|音视频", "电器"),
    (r"灯|照明|LED", "灯具灯串"),
    (r"家具|床垫|沙发|橱柜|桌|椅", "家具"),
    (r"服装|服饰|纺织|针织|羽绒|鞋|袜|内衣|睡衣|居家服|床上用品|毛巾|口罩|护具|箱包", "服装纺织"),
    (r"燃气|液化石油气|灶具", "燃气器具"),
    (r"打火机|烟花|爆竹", "烟花爆竹"),
    (r"眼镜|老视|太阳镜", "防护用品"),
    (r"头盔|劳动防护|防护服|安全帽|安全带|安全网|消防|灭火器", "防护用品"),
    (r"自行车|电动车|机动车|轮胎|车用|汽车|摩托|燃油|润滑油|汽油|柴油|制动|平衡车", "机动车及配件"),
    (r"化妆|牙刷|牙膏|洗涤|清洁剂|卫生用品|纸巾|湿巾|卫生巾|尿", "化妆品"),
    (r"餐具|厨具|锅|保温杯|(?<!非)食品接触|厨房", "厨房用品"),
    (r"首饰|珠宝|黄金", "首饰配饰"),
    (r"涂料|胶粘剂|地板|瓷砖|陶瓷|防水|门|窗|卫浴|水嘴|管材|管件|水泥|钢筋|玻璃|人造板|纤维板|刨花板|胶合板|壁纸|建筑|装修|电工套管|墙体|砖|砌块|花洒|水槽|散热器|密封|橡胶", "建材装修"),
    (r"工具|机床|电动工具|砂轮|焊机|压缩机|泵|阀门|紧固件|钢丝绳|机械|包装物|收割机|脱粒机", "机械工具"),
    (r"化肥|肥料|磷肥|磷酸|农药|农膜|农资|种子|饲料|农业", "农资"),
]


def nf_types(text):
    out = [name for name, rx in NF_RULES if re.search(rx, text or "")]
    return out[:3] or ["其他"]


def nf_group(cat, product):
    t = f"{cat or ''} {product or ''}"
    for rx, g in NF_GROUPS:
        if re.search(rx, t):
            return g
    return "其他非食品"


PROG = {  # source, kind of notice, action
    "samr_food": ("CN", "监督抽检不合格"),
    "samr_quality": ("CN", "国家监督抽查不合格"),
    "sz_food": ("SZ", "深圳市监督抽检不合格"),
    "sz_quality": ("SZ", "深圳市监督抽查不合格"),
}


def rows():
    cols = ("id,notice_url,notice_date,item_no,maker,maker_role,product,problem,test_value,standard_value,"
            "seller,platform,origin,spec,brand,prod_date,category,sample_no,disputed,dispute_note,raw,source,program,lab,maker_addr")
    out = []
    for c in db.fetch_table("cn_checks", cols, "&passed=is.false&order=id"):
        note = _clean(c.get("dispute_note"))
        disputed = bool(c.get("disputed") and note)
        upheld = disputed and bool(UPHELD.search(note)) and not NOT_UPHELD.search(note)
        maker = (c.get("maker") or "").strip("，；、 ")
        prob = c.get("problem") or ""
        x = prob or ("不合格" if (c.get("program") or "samr_food").endswith("food") else "不合格，具体项目见原文")
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
        prog = c.get("program") or "samr_food"
        src, act = PROG.get(prog, ("CN", "监督抽检不合格"))
        food = prog.endswith("food")
        if not food:
            if c.get("maker_addr") and len(c["maker_addr"]) <= 12:
                bits.append("标称生产单位所在地：" + c["maker_addr"])
            if c.get("lab"):
                bits.append("承检机构：" + c["lab"])
            if c.get("dispute_note") and not disputed:
                bits.append("备注：" + c["dispute_note"])
        key = c.get("sample_no") if food and c.get("sample_no") else f"{c['notice_url']}#{c['item_no']}"
        out.append({
            "id": src + "-" + hashlib.sha1(key.encode()).hexdigest()[:14],
            "src": src, "pub_date": c["notice_date"], "grp": "食品" if food else nf_group(c.get("category"), c.get("product")),
            "ind": c.get("category") or "", "product": c.get("product") or "", "product_orig": "",
            "problems": problem_types(prob, c.get("standard_value")) if food else nf_types(prob),
            "detail": x, "legal_limit": c.get("standard_value") or "", "quantity": "", "firm": maker,
            "importer": "", "lab_tested": True, "entry_no": "", "action": act, "url": c["notice_url"],
            "machine_translated": False, "ntype": nt, "note": "；".join(bits)[:800],
        })
    return out
