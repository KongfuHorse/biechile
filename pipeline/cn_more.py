"""More mainland sources, downloaded by the NAS ('pages' jobs) and parsed here into cn_checks:

  samr_quality  SAMR national product quality spot checks (国家监督抽查), Excel list of failed products
  sz_food       Shenzhen market regulator food sampling notices, Excel list of all samples (failed kept)
  sz_quality    Shenzhen market regulator product quality spot checks, PDF list of all samples (failed kept);
                the failed test items are only given per product type in the notice text

Run: python -m pipeline.cn_more            (parse + store)
     python -m pipeline.cn_more --dry out  (parse, write out/cn_more.json, store nothing)
"""
import base64
import datetime
import html as htmllib
import io
import json
import os
import re
import sys

import requests

from . import cn_samr, db

LIST_SAMR = ("https://www.samr.gov.cn/api-gateway/jpaas-publish-server/front/page/build/unit?webId=29e9522dc89d4e088a953d8cede72f4c"
             "&pageId={pid}&parseType=bulidstatic&pageType=column&tagId=ajax%E5%88%86%E9%A1%B5&tplSetId=5c30fb89ae5e48b9aefe3cdf49853830"
             '&paramJson={{"pageNo":{n},"pageSize":100}}')
SAMR_COLUMNS = ("f408ad3907c74da6a72f13557869012d", "5ceac0a356d84eb0b93eda0070a24489")  # 监督抽查不合格产品发布, 本司公告
SZ_FOOD = "https://amr.sz.gov.cn/xxgk/qt/ztlm/zdlygk/sygk/spzl_zd/"
SZ_QUAL = "https://amr.sz.gov.cn/xxgk/qt/ztlm/zlzl/jgtb_cp/"
FROM_YEAR = 2020


def program(url):
    if "samr.gov.cn" in url and "/zljds/" in url and "/art/" in url:
        return "samr_quality"
    if "/spzl_zd/content/" in url:
        return "sz_food"
    if "/jgtb_cp/content/" in url:
        return "sz_quality"
    return None


def _text(html):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)
    t = re.sub(r"<(br|/p|/div|/tr|/li|/h\d)\b[^>]*>", "\n", t)
    t = htmllib.unescape(re.sub(r"<[^>]+>", "", t)).replace("　", " ").replace("\xa0", " ")
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", t))


def _title(html):
    m = re.search(r'<meta name="ArticleTitle" content="([^"]+)"', html) or re.search(r"<title>(.*?)</title>", html, re.S)
    t = re.sub(r"\s+", "", htmllib.unescape(m.group(1))) if m else ""
    return re.sub(r"[-_|]深圳市市场监督管理局.*$|[-_|]国家市场监督管理总局.*$", "", t)


def _date(html, text):
    for pat in (r'<meta name="PubDate" content="(\d{4})-(\d{2})-(\d{2})', r'<meta name="firstpublishedtime" content="(\d{4})-(\d{2})-(\d{2})',
                r"(?:发布日期|发布时间|日期)[:：]\s*(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})"):
        m = re.search(pat, html) or re.search(pat, text)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def downloads(since=None):
    """(url, html, [(name, ext, bytes)]) of every notice page the NAS downloaded (jobs created on or after
    since, if given); newest download wins."""
    jobs = db.fetch_table("nas_jobs", "id", "&kind=eq.pages&status=eq.done&order=id.desc" + (f"&created_at=gte.{since}" if since else ""))
    seen = set()
    for row in jobs:
        r = requests.get(f"{db.URL}/rest/v1/nas_jobs?select=result&id=eq.{row['id']}", headers=db._h(), timeout=120)
        r.raise_for_status()
        res = (r.json()[0]["result"] or {}).get("results", [])
        res = [it for it in res if program(it.get("url", "")) and it.get("html") and it["url"] not in seen]
        if not res:
            continue
        files = {}
        if any(d.get("file") for it in res for d in it.get("docs", [])):
            f = requests.get(f"{db.URL}/rest/v1/nas_files?select=name,b64&job_id=eq.{row['id']}", headers=db._h(), timeout=180)
            f.raise_for_status()
            files = {x["name"]: x["b64"] for x in f.json()}
        for it in res:
            seen.add(it["url"])
            docs = [(d["name"], d["ext"], base64.b64decode(files[d["file"]])) for d in it.get("docs", []) if d.get("file") in files]
            yield it["url"], it["html"], docs


# ---------- sheets ----------

COLS = {
    "序号": "seq", "产品种类": "category", "产品类型": "category", "受检单位": "seller", "受检单位名称": "seller",
    "被抽样单位名称": "seller", "受检单位详细地址": "seller_addr", "标称生产单位": "maker", "标称生产单位名称": "maker",
    "（标称）生产单位名称": "maker", "(标称)生产单位名称": "maker", "标称生产企业名称": "maker", "标称生产单位所在地": "maker_addr",
    "标称生产单位地址": "maker_addr", "标称生产企业地址": "maker_addr", "产品名称": "product", "样品名称": "product",
    "规格型号": "spec", "型号规格等级": "spec", "型号规格": "spec", "生产日期/批号": "prod_date", "生产日期": "prod_date",
    "批号/生产日期/购进日期": "prod_date", "主要不合格项目": "problem", "不合格项目": "problem", "承检机构": "lab",
    "检验机构": "lab", "电商平台": "platform", "备注": "note", "标称文字商标": "brand", "标称商标": "brand", "商标": "brand",
    "抽样单号": "sample_no", "抽样编号": "sample_no", "检验结果": "result", "检验情况": "result", "食品分类": "category_food",
    "食品细类": "category_food", "检验值": "test_value", "标准值": "standard_value",
}


def _cell(v):
    return cn_samr._cell(v)


def _rows_from_table(table):
    """[dict] from a list of rows; header row found by its 序号 cell."""
    out, cols = [], None
    for raw in table:
        vals = [_cell(v) for v in raw]
        names = [re.sub(r"\s", "", v or "") for v in vals]
        if "序号" in names and sum(1 for n in names if n in COLS) >= 4:
            cols = [COLS.get(n) for n in names]
            continue
        if cols is None or not any(vals):
            continue
        d = {c: v for c, v in zip(cols, vals) if c and v}
        if d.get("product") and (d.get("maker") or d.get("seller")) and re.match(r"\d+$", str(d.get("seq") or "")):
            out.append(d)
    return out


def sheet_rows(data):
    try:
        if data[:4] == b"PK\x03\x04":
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
            tables = [list(ws.iter_rows(values_only=True)) for ws in wb.worksheets]
        else:
            import xlrd
            wb = xlrd.open_workbook(file_contents=data)
            tables = [[sh.row_values(i) for i in range(sh.nrows)] for sh in wb.sheets()]
    except Exception as e:
        print("  cannot read sheet:", e)
        return []
    return [r for t in tables for r in _rows_from_table(t)]


def pdf_rows(data):
    import pdfplumber
    rows = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for pg in pdf.pages:
            for t in pg.extract_tables():
                rows += [[(c or "").replace("\n", "") for c in r] for r in t]
    # the header repeats on each page, so parse page by page as one table
    return _rows_from_table(rows)


def failed(d):
    r = d.get("result") or ""
    if d.get("problem"):
        return True
    return "不合格" in r and not re.search(r"未发现不合格|^合格", r)


# ---------- Shenzhen quality: failed items per product type from the notice text ----------

def items_by_type(text):
    """{product type: '不合格项目有：...'} from sections like '（五）通用电源 ... 不合格项目有：...。'"""
    out = {}
    parts = re.split(r"\n\s*[（(]([一二三四五六七八九十]+)[)）]\s*", text)
    for i in range(2, len(parts), 2):
        body = parts[i]
        name = body.split("\n", 1)[0].strip()
        m = re.search(r"不合格项目(?:有|为|主要有|主要为)?[:：](.*?)(?:。|\n|$)", body)
        if name and m:
            out[name] = m.group(1).strip()
    return out


def _type_items(cat, table):
    if not cat:
        return ""
    for k, v in table.items():
        if k and (k in cat or cat in k):
            return v
    return ""


# ---------- one notice ----------

def parse_notice(url, html, docs):
    prog = program(url)
    text = _text(html)
    title = _title(html)
    date = _date(html, text)
    years = [int(y) for y in re.findall(r"(20\d{2})年", title)]
    if prog == "samr_quality" and (not years or min(years) < FROM_YEAR):
        return []
    if date and date[:4] < str(FROM_YEAR):
        return []
    m = re.search(r"(深市监通告〔\d{4}〕\d+号|国市监[^\n]{0,20}〔\d{4}〕\d+号)", text)
    no = m.group(1) if m else None
    per_type = items_by_type(text) if prog == "sz_quality" else {}
    out = []
    for fi, (name, ext, data) in enumerate(docs, 1):
        if prog == "samr_quality" and not re.search(r"不合格产品", name):
            continue  # skip lists of firms that refused inspection or failed twice
        if ext in ("xlsx", "xls"):
            rows = sheet_rows(data)
        elif ext == "pdf" and prog == "sz_quality":
            rows = pdf_rows(data)
        else:
            continue
        for i, d in enumerate(rows, 1):
            if not failed(d):
                continue
            problem = d.get("problem")
            if not problem and prog == "sz_quality":
                it = _type_items(d.get("category"), per_type)
                problem = ("该类产品不合格项目有：" + it) if it else None
            if not problem and prog == "sz_food":
                problem = re.sub(r"^不合格[，,；;：:\s]*", "", d.get("result") or "") or None
            out.append({
                "notice_url": url, "notice_title": title, "notice_no": no, "notice_date": date, "item_no": fi * 1000 + i,
                "program": prog, "source": ext, "attachment": name, "maker": d.get("maker"), "maker_addr": d.get("maker_addr"),
                "maker_role": f"生产:{d['maker']}" if d.get("maker") else None, "product": d.get("product"),
                "problem": problem, "test_value": d.get("test_value"), "standard_value": d.get("standard_value"),
                "seller": d.get("seller"), "seller_addr": d.get("seller_addr"), "platform": d.get("platform"),
                "spec": d.get("spec"), "brand": d.get("brand"), "prod_date": d.get("prod_date"), "lab": d.get("lab"),
                "category": d.get("category") or d.get("category_food"), "sample_no": d.get("sample_no"),
                "disputed": False, "passed": False, "dispute_note": d.get("note"),
                "raw": json.dumps(d, ensure_ascii=False),
            })
    return out


def collect(since=None):
    rows, notices, empty = [], 0, []
    for url, html, docs in downloads(since):
        notices += 1
        got = parse_notice(url, html, docs)
        if not got and docs:
            empty.append(url)
        rows += got
    return rows, notices, empty


def main():
    dry = "--dry" in sys.argv
    rows, notices, empty = collect()
    from collections import Counter
    print(f"notices read: {notices}; failed rows: {len(rows)}; by programme: {dict(Counter(r['program'] for r in rows))}")
    for u in empty[:30]:
        print("  no failed rows:", u)
    if dry:
        out = sys.argv[sys.argv.index("--dry") + 1] if len(sys.argv) > sys.argv.index("--dry") + 1 else "out"
        os.makedirs(out, exist_ok=True)
        json.dump(rows, open(os.path.join(out, "cn_more.json"), "w"), ensure_ascii=False, indent=1)
    else:
        cn_samr.store(rows)
        print("stored")


if __name__ == "__main__":
    main()
