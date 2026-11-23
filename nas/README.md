# biechile NAS 代理

国内 NAS（极空间 Z4）上的抓取代理。它每隔几十秒去 Supabase 领任务、交结果，不需要开放任何端口。

## 组成

| 文件 | 作用 | 怎么更新 |
|---|---|---|
| `image/bootstrap.py` | 代理本体：心跳、领任务、下载代码包、执行、回传 | 改了以后 GitHub 自动构建镜像推到 Docker Hub，NAS 上要重新下载镜像（很少需要） |
| `image/Dockerfile` | 基础镜像：Python + 无头 Chromium + 中文字体 | 同上 |
| `jobs/jobs/` | 任务代码包：`net`、`probe`、`fetch` 等 | 改了以后 GitHub 自动打包存进 Supabase，NAS 一分钟内自动换上，不用碰 NAS |
| `publish_code.py` | 打包并发布任务代码 | GitHub Actions 调用 |
| `../supabase/schema_nas.sql` | 任务表和 NAS 专用数据库功能 | |
| `nettest.sh` | 一次性的连通性测试脚本 | |

## 安全设计

- NAS 上不放数据库总密钥，只放一个 NAS 专用口令。这个口令只能调用 `nas_*` 这几个功能：心跳、领任务、交结果、上传截图、下载代码包。拿到它也读不了、改不了网站的其他数据。
- 代理不执行数据库里发来的命令，只能运行代码包里已有的任务类型。代码包只有持有总密钥的 GitHub 流程能发布，下载后还会核对 sha256。
- 遇到验证码、滑块就停下并报告，不做任何破解。

## 一、准备 Docker Hub（只做一次）

1. 在 https://hub.docker.com 注册免费账号。
2. 右上角头像 → Account settings → Personal access tokens → Generate new token。
   描述填 `biechile github`，权限选 **Read & Write**，生成后复制令牌。令牌只显示一次。
3. 打开 https://github.com/KongfuHorse/biechile → Settings → Secrets and variables → Actions → New repository secret，添加两个：
   - `DOCKERHUB_USERNAME`：你的 Docker Hub 用户名
   - `DOCKERHUB_TOKEN`：刚才复制的令牌

## 二、在极空间里创建容器

### 1. 下载镜像
Docker → 镜像 → 搜索 `你的Docker Hub用户名/biechile-nas` → 标签 `latest` → 下载。约 1 GB。

### 2. 准备数据文件夹
在"个人空间"里新建文件夹 `biechile-nas`。代理会在里面存代码、日志和抓到的网页原件。

### 3. 创建容器
容器 → 创建 → 选 `biechile-nas:latest`，然后按标签逐个填：

| 标签 | 怎么填 |
|---|---|
| 通用 | 容器名称 `biechile-nas`。如果有"自动重启/开机启动"，打开。如果能限制内存，填 3 GB。 |
| 文件夹路径 | 添加一条：NAS 上选刚建的 `biechile-nas` 文件夹，容器内路径填 `/data`，权限选读写。 |
| 网络 | 保持默认（bridge）。 |
| 端口 | 不用加。 |
| 别名 | 不用填。 |
| 环境 | 添加下面 4 个变量（值见下表）。 |
| 命令 | **保持"默认"**，不要像 nettest 那样填 sleep。 |
| 能力 | 保持默认。 |

环境变量：

| 名称 | 值 |
|---|---|
| `SUPABASE_URL` | `https://arfagbvdcooyudfyyupb.supabase.co` |
| `SUPABASE_ANON_KEY` | 网站本来就公开的 publishable key，部署时给你 |
| `NAS_TOKEN` | NAS 专用口令，部署时单独给你 |
| `AGENT_NAME` | `nas1` |

点"应用"。卡片显示"运行中"就好了。

### 4. 确认
点容器卡片上的"日志"，应该看到：
```
agent nas1 started, boot boot-1, code -, handlers []
installed code xxxxxxxxxxxx
restarting
agent nas1 started, boot boot-1, code xxxxxxxxxxxx, handlers ['fetch', 'net', 'probe']
```
之后就由数据库派任务，不用再操作 NAS。

## 派任务（给开发者）

```sql
insert into nas_jobs (kind, args) values
  ('probe', '{"urls": ["https://spcjsac.gsxt.gov.cn/"], "delay": 4}');
select id, status, result, log from nas_jobs order by id desc limit 5;
select name, last_seen, version, info from nas_agents;
```
截图在 `nas_files`（base64）。
