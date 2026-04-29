# AI 第二大脑 (Second Brain)

一款可私有部署的 AI 第二大脑。汇聚多设备行为与信息流，自动理解"你在做什么与为什么"，每天生成工作/生活动线、事项进展与新知识总结，持续构建个人知识图谱，并将总结转化为可执行的计划与建议。

## 功能

- **数据采集**：Chrome/Safari 浏览历史导入 / Google Calendar 采集 / Gmail 邮件采集 / Git 仓库或工作区提交记录采集 / 手动输入
- **意图理解**：AI 自动推断活动类别、意图和主题标签
- **每日总结**：时间线、事项进展、新知识提取、时间分布统计
- **知识图谱**：增量构建个人知识网络，自动关联项目/概念/工具
- **计划建议**：带优先级的明日计划 + 注意力与学习优化建议
- **LLM 切换**：支持 OpenAI API / Ollama 本地模型
- **数据管理**：数据可浏览、可删除，信息自主可控

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
# 编辑 .env，填入 OpenAI API Key 或 Ollama 配置

# 启动服务
uvicorn app.main:app --reload --port 8000
```

服务启动后访问 http://localhost:8000/docs 查看 API 文档。

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
| POST | `/api/ingest/manual` | 手动输入活动记录 |
| GET | `/api/events` | 查询活动事件 |
| POST | `/api/analysis/run` | 运行 AI 意图分析 |
| POST | `/api/summary/generate` | 生成每日总结 |
| GET | `/api/summary/{date}` | 获取每日总结 |
| GET | `/api/knowledge/graph` | 获取知识图谱 |
| GET | `/api/knowledge/node/{id}` | 节点详情 |
| POST | `/api/plan/generate` | 生成明日计划 |
| PUT | `/api/plan/{id}` | 编辑计划 |
| GET | `/api/data/overview` | 数据概览 |
| DELETE | `/api/data/events/{id}` | 删除单条事件 |
| DELETE | `/api/data/day/{date}` | 删除整天数据 |
| GET | `/api/settings` | 获取设置 |
| PUT | `/api/settings` | 更新设置 |

## 使用流程

```
1. 导入数据 → 2. AI 分析 → 3. 生成总结 → 4. 查看图谱 → 5. 获取计划
```

1. 选择一种方式导入活动数据（推荐直接用 Chrome、Google Calendar、Gmail 或手动输入）
2. 对指定日期运行 AI 意图分析
3. 生成每日总结（自动提取知识图谱）
4. 查看知识图谱中的实体和关系
5. 基于总结生成明日计划和优化建议

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

完成一次 Chrome 登录并启动 Chrome MCP 后，可以在“干了啥”页面点击“一键采集数据”。普通数据源会先完成并刷新列表，随后前端按小批次调用 `chrome-devtools-history` 补充 Chrome 内网历史明细，每批完成后都会先写入数据库并刷新下方事件。后端会优先通过 `http://127.0.0.1:12306/mcp` 调用 Chrome MCP 的 `chrome_history` 和 `chrome_get_web_content`，复用已登录浏览器会话读取最近 2 天的内网历史和渲染正文；如果 MCP 不可用，再回退到 `127.0.0.1:9222` DevTools 端口方式。采集内容包括标题结构、正文、表格、表单字段和列表内容。这样可以把 Space、审批、工单、项目页这类只在浏览器登录态下可见的工作内容补进事件正文。MCP 采集过程中临时打开的页面会在每页抓取后自动关闭，避免 Chrome 标签页堆积。

接口也可以直接调用：

```bash
curl -X POST http://127.0.0.1:8000/api/ingest/chrome-devtools-history \
  -H 'content-type: application/json' \
  -d '{"days":2,"max_pages":10,"offset":0,"intranet_only":true}'
```

如果历史记录已经通过普通 Chrome History 导入过，该接口会用更详细的渲染正文更新已有事件，而不是只按重复记录跳过。默认会优先采集常见内网域名和本地域名；需要限定公司域名时可传入 `domains`，例如 `{"domains":["shopee.io","shopee.com"]}`。

### Gmail 数据源

Gmail 复用配置页上传的 Google OAuth JSON 和 Google 邮箱地址。授权时会同时申请 Calendar 只读和 Gmail 只读权限，因此完成一次“授权 Google 数据源”后，日历和 Gmail 都可以被一键采集使用。

在“配置下”开启 `Gmail`，确认已填写 Google 邮箱、上传 OAuth JSON，并完成 Google 数据源授权。之后“干了啥”页面的一键采集会读取最近 2 天的 Gmail 邮件，写入 source=`gmail` 的事件。采集内容包括主题、收发件人、摘要、正文片段、附件名和 Gmail 链接；重复邮件会按链接更新已有事件。

接口也可以直接调用：

```bash
curl -X POST http://127.0.0.1:8000/api/ingest/gmail \
  -H 'content-type: application/json' \
  -d '{"days":2,"max_messages":100}'
```

如果之前只授权过 Google Calendar，需要在配置页重新点击“授权 Google 数据源”，让 token 补上 Gmail 只读权限。

## 技术栈

- **前端**：React / Vite / TailwindCSS
- **后端**：Python / FastAPI / SQLAlchemy / SQLite
- **LLM**：OpenAI SDK / Ollama HTTP API
- **测试**：pytest / pytest-asyncio

## macOS App 打包

本项目可以打成本机 `.app` 桌面壳：Swift/WKWebView 负责窗口，App 启动时拉起内置 FastAPI，后端直接托管前端静态文件。

```bash
./scripts/build_mac_app.sh
open "dist/mac/Second Brain.app"
```

运行数据会写入 `~/Library/Application Support/Second Brain`。Google Calendar 凭据可在 App 的 `配置下` 页面上传保存，授权 token 也会保存在应用支持目录里。

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
