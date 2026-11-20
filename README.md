# biechile.com

中国产品境外通报汇总。汇集各国家和地区监管机构公布的中国产品边境不合格、拒收通报。

## 数据来源

| 代码 | 来源 | 方式 |
|---|---|---|
| TW | 台湾食品药物管理署 边境检验不符合食品资讯 | 逐条读取详情页 |
| US | 美国 FDA Data Dashboard 进口拒收（Import Refusals） | 官方 API，需要 key |

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

1. 抓台湾新增的通报，抓 FDA 最近 30 天的拒收记录
2. 写进 Supabase（按记录编号去重）
3. 从 Supabase 导出 `site/data/*.json`
4. 部署到 GitHub Pages

手动补历史数据：Actions → Daily update and deploy → Run workflow，填起始日期（如 `2023-01-01`）。

## 需要的设置

仓库 Settings → Secrets and variables → Actions：

- Secrets：`SUPABASE_URL`、`SUPABASE_SERVICE_KEY`、`FDA_USER`、`FDA_KEY`
- Variables：`CF_BEACON_TOKEN`（Cloudflare Web Analytics 的 token，可选）

## 新术语

每次运行后，Supabase 的 `runs` 表里 `source = 'terms'` 的记录会列出没有翻译的 FDA 产品名称和代码。把翻译加进 `ref/fda_product_zh.json` 或 `pipeline/normalize.py` 即可。

## 本地测试

```bash
pip install -r requirements.txt
export FDA_USER=... FDA_KEY=...
python -m pipeline.run --since 2026-01-01   # 没有 Supabase 设置时，数据存到 local_data/
cd site && python -m http.server            # 打开 http://localhost:8000
```
