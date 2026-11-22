# biechile.com

中国产品境外通报汇总。汇集各国家和地区监管机构公布的中国产品边境不合格、拒收通报。

## 数据来源

| 代码 | 来源 | 方式 |
|---|---|---|
| TW | 台湾食品药物管理署 边境检验不符合食品资讯 | 逐条读取详情页 |
| US | 美国 FDA Data Dashboard 进口拒收（Import Refusals） | 官方 API，需要 key |
| JP | 日本厚生劳动省 输入食品等の食品卫生法违反事例（进口时） | 每个财年一个 Excel，每月更新 |
| EU | 欧盟 RASFF Window 公开通报，原产国为中国 | 公开 JSON 接口，不需要 key；没有企业名 |
| KR | 韩国食药处 进口食品不合格（수입식품부적합） | 读取列表网页；官方只保留约半年，每天保存 |
| SFA | 新加坡食品局 食品召回（新加坡不公布进口拒收） | 新闻室 JSON 接口；Haiku 从正文提取产品，只留原产国中国；撤销的召回标"召回已撤销" |
| SG | 欧盟 Safety Gate 非食品危险产品，原产国中国 | 官方每周 XML 报告；有品牌、型号、条码、销售平台、照片（照片直接用欧盟官方地址） |

欧盟 RASFF 产品图片：每日任务打开通报措施里附的警示页面，收集图片，Haiku 判断是否为产品照片，压缩成 WebP 存在 Supabase Storage 的 `rasff` 桶（表 `record_images`、`image_pages`）。后台"产品图片"里通过的图片，在部署时复制到网站的 `img/` 目录。

日本、欧盟、韩国的产品名、问题描述用 Claude Haiku 翻译并归类问题类型，存在 `term_translations`（kind 为 `jp_*`、`eu_*`、`kr_*`），网站标"机翻"，可以在后台"翻译核对"里修改。

## 结构

```
pipeline/         数据处理
  sources.py      从官方网站或 API 抓取原始数据
  normalize.py    统一格式、繁转简、术语对照、问题分类
  db.py           存储（Supabase；没有配置时用本地文件）
  export.py       生成网页用的 JSON（每年一个文件）
  run.py          每日任务入口
ref/              对照表
  fda_product_zh.json   FDA 产品名称中英对照
  fda_charges.csv       FDA 拒收原因代码表
supabase/schema.sql     数据库建表语句
site/             网站（GitHub Pages 发布这个目录）
.github/workflows/update.yml   每天自动更新和部署
```

## 自动更新

GitHub Actions 每天跑一次：

1. 抓台湾新增的通报，FDA 最近 30 天，日本最近 60 天，欧盟最近 30 天，韩国官网现有的全部中国记录
2. 写进 Supabase（按记录编号去重）
3. 从 Supabase 导出 `site/data/*.json`
4. 部署到 GitHub Pages

手动补历史数据：Actions → Daily update and deploy → Run workflow，填起始日期（如 `2023-01-01`）。只补某几个来源时，在 skip 里填不需要的来源，例如 `tw us`。

## 需要的设置

仓库 Settings → Secrets and variables → Actions：

- Secrets：`SUPABASE_URL`、`SUPABASE_SERVICE_KEY`、`FDA_USER`、`FDA_KEY`、`ANTHROPIC_API_KEY`（新名称机器翻译用，可选）
- Variables：`CF_BEACON_TOKEN`（Cloudflare Web Analytics 的 token，可选）

## 新术语

对照表（`ref/fda_product_zh.json`、`pipeline/normalize.py`）里没有的 FDA 产品名称、行业类别和拒收原因代码：

1. 有 `ANTHROPIC_API_KEY` 时，用 Claude Haiku 5.5 自动翻译，存进 Supabase 的 `term_translations` 表（`status = 'machine'`），网页上显示"机翻"标记。
2. 人工核对：在 `term_translations` 里改好 `zh`，把 `status` 改成 `verified`；或者把译文加进对照表文件。
3. 没有 key 时，新名称显示英文原文，并记在 `runs` 表 `source = 'terms'` 的记录里。

台湾的农药、兽药名称（台湾用词转大陆用词）不能自动发现，仍然靠 `TW_TERMS` 人工维护。

## 本地测试

```bash
pip install -r requirements.txt
export FDA_USER=... FDA_KEY=...
python -m pipeline.run --since 2026-01-01   # 没有 Supabase 设置时，数据存到 local_data/
cd site && python -m http.server            # 打开 http://localhost:8000
```
