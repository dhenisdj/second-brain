# AI 第二大脑 (Second Brain)

一款可私有部署的 AI 第二大脑。汇聚浏览器、日历、邮件、Git 与手动补记等工作信息流，自动理解"你在做什么与为什么"，每天生成工作日程、事项进展、知识沉淀与时间投入分析，持续构建个人知识图谱，并将昨天的总结转化为今天可执行的计划与建议。

## 功能

- **自动数据采集**：Chrome/Safari 浏览记录、Google Calendar、Gmail、Git 仓库或工作区提交记录、手动补记
- **定时自动化**：每天凌晨 3 点采集并总结前一天事项，再基于昨天总结生成今天计划；当天每 4 小时刷新当天采集与总结
- **意图理解**：AI 自动推断活动类别、意图和主题标签，高频浏览记录会先按主题聚合再进入总结
- **结构化总结**：工作日程竖向时间轴、按项目分组的进展/问题/风险/下一步、知识沉淀、时间分布统计
- **知识图谱**：增量构建个人知识网络，实体归一化后自动关联项目、概念、工具和人物
- **计划建议**：基于前一天总结生成次日计划，支持优先级、状态、预计时长、建议时段和手动新增计划
- **整理归档**：按年份 + 季度、月份、日期的多级结构整理历史记录
- **后台任务**：异步总结、计划、图谱刷新/重建与定时任务统一进入任务队列，可在前端查看最近任务
- **LLM 切换**：支持 OpenAI API、DeepSeek API 与 Ollama 本地模型
- **桌面应用**：可打包为 macOS App，内置 FastAPI 后端和前端静态资源，运行数据保存在应用支持目录
- **数据管理**：数据可浏览、可删除，信息自主可控

## 产品页面

| 页面 | 说明 |
|---|---|
| 干了啥 | 查看当天活动流。默认依赖定时任务自动采集，页面上的“手动补采”和“补记一条”只作为缺数据或补漏时使用的备用入口。 |
| 总结下 | 查看每日结构化总结，包括工作日程、事项进展、知识沉淀和时间分布。手动刷新总结是备用操作，日常由后台任务自动生成。 |
| 沉淀下 | 查看个人知识图谱。图谱使用力导向布局和实体类型聚类，节点可查看证据、相邻节点和来源摘要。 |
| 规划下 | 默认选择昨天作为总结日期，用昨天总结生成今天计划。生成后可编辑计划项，也可在计划列表下方手动新增计划。 |
| 整理下 | 按年份 + Q1/Q2/Q3/Q4、月份、具体日期多级展开历史数据，方便回看已分析、已总结和待处理日期。 |
| 配置下 | 配置 LLM、浏览器、Google Calendar/Gmail、Git 数据源和授权状态。 |

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18.19+
- Chrome 浏览器
- (可选) Ollama — 如果需要使用本地模型
- (可选) Graphiti MCP — 如果需要专业的时间感知知识图谱后端

### 启动前置配置：Chrome MCP Native Messaging Bridge

如果需要让本项目在本机调试或采集内网页面时复用已登录 Chrome，请先配置 Chrome MCP Server。该流程参考了[《Chrome MCP Server完全安装指南》](https://zhuanlan.zhihu.com/p/1945244696445182752)，这里仅保留本项目启动需要的步骤。

1. 安装 Node.js 和 pnpm：

```bash
brew install node
brew install pnpm

node --version
pnpm --version
```

2. 安装 Chrome MCP 扩展：

- 打开 https://github.com/hangwin/mcp-chrome/releases
- 下载并解压 `mcp-chrome-extension.zip`
- 在 Chrome 打开 `chrome://extensions/`
- 开启“开发者模式”
- 点击“加载已解压的扩展程序”，选择解压后的扩展目录

3. 使用 pnpm 安装 Native Messaging Bridge：

```bash
pnpm config set enable-pre-post-scripts true
pnpm add -g mcp-chrome-bridge

mcp-chrome-bridge --version
```

如果 `mcp-chrome-bridge` 命令找不到，先配置 pnpm 全局命令路径：

```bash
pnpm setup
exec $SHELL -l
mcp-chrome-bridge --version
```

如果扩展仍显示未连接，手动注册一次 Bridge：

```bash
mcp-chrome-bridge register
```

4. 启动 Chrome MCP 本地服务：

- 点击 Chrome 扩展栏里的 MCP 图标
- 点击 `Connect`
- 默认服务地址为 `http://127.0.0.1:12306/mcp`

5. 验证连接：

```bash
which mcp-chrome-bridge
curl -s http://127.0.0.1:12306/mcp/health || echo "Chrome MCP 服务未启动"
lsof -i :12306
```

Claude Code 可按需添加 MCP 服务：

```bash
claude mcp add --transport http chrome-mcp http://127.0.0.1:12306/mcp
claude mcp list
```

### 可选配置：Graphiti Knowledge Graph MCP

项目默认仍使用本地 SQLite 轻量图谱展示。若要启用更专业的实体/关系抽取和时间感知记忆，可以额外启动 Graphiti MCP，并让本项目在图谱刷新/重建时把每日总结与证据事件发布为 Graphiti episode。

先启动 FalkorDB，或改用 Neo4j 配置：

```bash
docker run --rm -p 6379:6379 falkordb/falkordb
```

另开一个终端启动 Graphiti MCP：

```bash
git clone https://github.com/getzep/graphiti.git
cd graphiti/mcp_server
uv sync
# 在 graphiti/mcp_server/.env 中配置 OPENAI_API_KEY / MODEL_NAME 后启动 MCP
uv run main.py --transport http --port 8001 --group-id second-brain
```

Graphiti MCP 启动后，在 `backend/.env` 中打开：

```bash
GRAPHITI_MCP_ENABLED=true
GRAPHITI_MCP_URL=http://127.0.0.1:8001/mcp/
GRAPHITI_MCP_GROUP_ID=second-brain
```

Graphiti 需要 FalkorDB 或 Neo4j。若使用 Graphiti 官方 Docker Compose 的默认 `8000` 端口，请把 Graphiti 或本项目后端改到不同端口，避免两个服务都占用 `8000`。

然后重启后端。可用以下接口检查或检索 Graphiti 记忆：

```bash
curl http://127.0.0.1:8000/api/knowledge/graphiti/status
curl "http://127.0.0.1:8000/api/knowledge/graphiti/search?q=Transformer&kind=facts"
```

### 自动化任务配置

项目启动后会按 `.env` 中的配置启动本地定时任务：

```bash
DAILY_AUTOMATION_ENABLED=true
DAILY_AUTOMATION_HOUR=3
DAILY_AUTOMATION_MINUTE=0
DAILY_AUTOMATION_TIMEZONE=Asia/Shanghai
DAILY_AUTOMATION_COLLECT_DAYS=2
CURRENT_DAY_REFRESH_ENABLED=true
CURRENT_DAY_REFRESH_INTERVAL_HOURS=4
CURRENT_DAY_REFRESH_COLLECT_DAYS=1
```

默认行为：

1. 每天 `03:00` 对前一天执行数据采集、AI 分析、总结生成、知识图谱刷新，并基于前一天总结生成当天计划。
2. 当天每 `4` 小时执行一次当天数据采集与总结刷新，不自动覆盖次日计划。
3. 同一日期、同一时间桶的定时任务会通过资源键去重，避免重复排队。
4. 前端右下角“后台任务”会展示最近任务状态，包括 `daily.pipeline`、`day.refresh`、`summary.generate`、`plan.generate`、`graph.refresh` 等。

### 后端启动

```bash
cd second-brain/backend

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
pip install greenlet

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入 OpenAI/DeepSeek API Key 或 Ollama 配置

# 启动服务
uvicorn app.main:app --reload --port 8000
```

服务启动后访问 http://localhost:8000/docs 查看 API 文档。

### 前端启动

```bash
cd second-brain/frontend
npm install
npm run dev -- --host 127.0.0.1
```

前端默认访问 http://127.0.0.1:5173。

### 运行测试

```bash
# 单元测试
python -m pytest tests/ -v

# E2E 测试
python -m pytest e2e/ -v
```

## API 概览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/ingest/chrome` | 上传 Chrome 浏览历史 |
| POST | `/api/ingest/chrome-devtools` | 采集 Chrome 当前已渲染标签页 |
| POST | `/api/ingest/chrome-devtools-history` | 使用已登录 Chrome 会话采集内网历史明细 |
| POST | `/api/ingest/gcal` | 采集已授权账号最近日历事件 |
| POST | `/api/ingest/gmail` | 采集已授权账号最近 Gmail 邮件 |
| POST | `/api/ingest/git` | 采集已配置仓库或工作区的 Git 提交记录 |
| POST | `/api/ingest/collect` | 按配置统一采集已启用数据源 |
| POST | `/api/ingest/manual` | 手动输入活动记录 |
| GET | `/api/events` | 查询活动事件 |
| POST | `/api/analysis/run` | 运行 AI 意图分析 |
| POST | `/api/summary/generate` | 生成每日总结 |
| POST | `/api/summary/generate-async` | 异步生成每日总结 |
| GET | `/api/summary/{date}` | 获取每日总结 |
| GET | `/api/summary/status/{date}` | 获取指定日期总结任务状态 |
| GET | `/api/knowledge/graph` | 获取知识图谱 |
| GET | `/api/knowledge/node/{id}` | 节点详情 |
| POST | `/api/knowledge/rebuild` | 同步重建知识图谱 |
| POST | `/api/knowledge/rebuild-async` | 异步重建知识图谱 |
| POST | `/api/plan/generate` | 生成次日计划 |
| POST | `/api/plan/generate-async` | 异步生成次日计划 |
| GET | `/api/plan/by-summary/{date}` | 通过总结日期查询对应计划 |
| PUT | `/api/plan/{id}` | 编辑计划 |
| GET | `/api/data/overview` | 数据概览 |
| DELETE | `/api/data/events/{id}` | 删除单条事件 |
| DELETE | `/api/data/day/{date}` | 删除整天数据 |
| GET | `/api/settings` | 获取设置 |
| POST | `/api/settings/google-credentials` | 上传 Google OAuth JSON |
| POST | `/api/settings/google-calendar/authorize` | 发起 Google 数据源授权 |
| PUT | `/api/settings` | 更新设置 |
| GET | `/api/jobs` | 查询后台任务列表 |
| GET | `/api/jobs/{id}` | 查询后台任务详情 |

## 使用流程

```
1. 配置数据源 → 2. 自动采集与刷新 → 3. 查看总结和图谱 → 4. 编辑今天计划 → 5. 整理回看历史
```

1. 在“配置下”启用 Chrome、Safari、Google Calendar、Gmail、Git 等数据源。
2. 后台定时任务会自动采集、分析和总结；“干了啥”的“手动补采”只在缺数据时使用。
3. 在“总结下”查看工作日程、事项进展、知识沉淀和时间分布。
4. 在“沉淀下”查看知识图谱中的实体、关系和证据。
5. 在“规划下”查看由昨天总结生成的今天计划，并按实际情况新增、编辑或保存计划项。
6. 在“整理下”按年/季度/月/日回看历史记录和处理状态。

### Chrome 当前标签页采集

公司内网页面通常依赖浏览器登录态，直接从 Chrome History 里的 URL 再请求页面时只能拿到登录页或空壳。可以用 Chrome DevTools 当前标签页采集补充已渲染正文：

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --profile-directory="Profile 1"
```

在这个 Chrome 窗口里打开并登录需要采集的内网页面，然后在“干了啥”页面点击“当前标签页”。该方式会读取本机 `127.0.0.1:9222` 上的已打开标签页，提取标题、可见文本、标题结构和表格摘要，并尽量用 Chrome 历史中的最近访问时间去重。

如果 Chrome 已经在运行，需先完全退出后再用上述命令启动；或者使用独立 `--user-data-dir` 启动一个专用窗口并在其中完成内网登录。

### Chrome 内网历史明细采集

完成一次 Chrome 登录并启动 Chrome MCP 后，定时任务或“干了啥”页面的“手动补采”会先完成普通数据源采集并刷新列表，随后前端按小批次调用 `chrome-devtools-history` 补充 Chrome 内网历史明细，每批完成后都会先写入数据库并刷新下方事件。后端会优先通过 `http://127.0.0.1:12306/mcp` 调用 Chrome MCP 的 `chrome_history` 和 `chrome_get_web_content`，复用已登录浏览器会话读取最近 2 天的内网历史和渲染正文；如果 MCP 不可用，再回退到 `127.0.0.1:9222` DevTools 端口方式。采集内容包括标题结构、正文、表格、表单字段和列表内容。这样可以把 Space、审批、工单、项目页这类只在浏览器登录态下可见的工作内容补进事件正文。MCP 采集过程中临时打开的页面会在每页抓取后自动关闭，避免 Chrome 标签页堆积。

接口也可以直接调用：

```bash
curl -X POST http://127.0.0.1:8000/api/ingest/chrome-devtools-history \
  -H 'content-type: application/json' \
  -d '{"days":2,"max_pages":10,"offset":0,"intranet_only":true}'
```

如果历史记录已经通过普通 Chrome History 导入过，该接口会用更详细的渲染正文更新已有事件，而不是只按重复记录跳过。默认会优先采集常见内网域名和本地域名；需要限定公司域名时可传入 `domains`，例如 `{"domains":["shopee.io","shopee.com"]}`。

### Gmail 数据源

Gmail 复用配置页上传的 Google OAuth JSON 和 Google 邮箱地址。授权时会同时申请 Calendar 只读和 Gmail 只读权限，因此完成一次“授权 Google 数据源”后，日历和 Gmail 都可以被采集任务使用。

在“配置下”开启 `Gmail`，确认已填写 Google 邮箱、上传 OAuth JSON，并完成 Google 数据源授权。之后定时任务或“干了啥”页面的“手动补采”会读取最近 2 天的 Gmail 邮件，写入 source=`gmail` 的事件。采集内容包括主题、收发件人、摘要、正文片段、附件名和 Gmail 链接；重复邮件会按链接更新已有事件。

接口也可以直接调用：

```bash
curl -X POST http://127.0.0.1:8000/api/ingest/gmail \
  -H 'content-type: application/json' \
  -d '{"days":2,"max_messages":100}'
```

如果之前只授权过 Google Calendar，需要在配置页重新点击“授权 Google 数据源”，让 token 补上 Gmail 只读权限。

### 知识图谱与实体归一化

每日总结完成后会触发知识图谱刷新。图谱抽取会先让 LLM 返回项目、人物、概念、工具和主题节点，再经过本地实体归一化层：

- `我`、`本人`、`user`、`current user` 等自指表达统一归并到 `我`。
- `用户`、`员工`、`申请人`、`审批人` 等泛化角色不会被误认为具体人物，必要时会转成 topic/concept。
- 已有节点的别名会作为候选，使用 `rapidfuzz` 做高置信匹配，减少同一实体的重复节点。
- 节点属性会保留 `canonical_name`、`aliases`、`normalized_from`、`resolution_method` 和置信度，方便后续排查。

前端“沉淀下”使用 @antv/g6 渲染力导向图，并按实体类型做聚类、颜色和引力差异化。点击节点可查看相邻节点、证据摘要和来源。

## 技术栈

- **前端**：React / Vite / TailwindCSS / @antv/g6 / react-vertical-timeline-component
- **后端**：Python / FastAPI / SQLAlchemy / SQLite
- **LLM**：OpenAI SDK / DeepSeek API / Ollama HTTP API
- **实体归一化**：rapidfuzz + 规则归一化
- **测试**：pytest / pytest-asyncio

## macOS App 打包

本项目可以打成本机 `.app` 桌面壳：Swift/WKWebView 负责窗口，App 启动时拉起内置 FastAPI，后端直接托管前端静态文件。

```bash
./scripts/build_mac_app.sh
open "dist/mac/Second Brain.app"
```

运行数据会写入 `~/Library/Application Support/Second Brain`。Google Calendar/Gmail 凭据可在 App 的 `配置下` 页面上传保存，授权 token 也会保存在应用支持目录里。App 启动时会拉起内置后端并托管前端静态资源，前端资源带缓存失效参数，重新打包后可看到最新 UI。

当前脚本会把 `backend/venv` 一起打进 App，适合本机打包和演示。若要发给其他 Mac 使用，应改为用 PyInstaller 或独立 Python runtime 打包后端，避免依赖本机 Python 路径。

## 项目结构

```
second-brain/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI 入口
│   │   ├── config.py         # 配置管理
│   │   ├── database.py       # 数据库
│   │   ├── models/           # ORM 模型
│   │   ├── routers/          # API 路由
│   │   ├── services/         # 业务逻辑
│   │   └── prompts/          # LLM Prompt 模板
│   ├── tests/                # 单元测试
│   └── e2e/                  # E2E 测试
└── CHANGELOG.md
```

## License

MIT
