# AI 第二大脑 (Second Brain)

一款可私有部署的 AI 第二大脑。汇聚多设备行为与信息流，自动理解"你在做什么与为什么"，每天生成工作/生活动线、事项进展与新知识总结，持续构建个人知识图谱，并将总结转化为可执行的计划与建议。

## 功能

- **数据采集**：Chrome/Safari 浏览历史导入 / Google Calendar 采集 / Git 提交记录采集 / 手动输入
- **意图理解**：AI 自动推断活动类别、意图和主题标签
- **每日总结**：时间线、事项进展、新知识提取、时间分布统计
- **知识图谱**：增量构建个人知识网络，自动关联项目/概念/工具
- **计划建议**：带优先级的明日计划 + 注意力与学习优化建议
- **LLM 切换**：支持 OpenAI API / Ollama 本地模型
- **数据管理**：数据可浏览、可删除，信息自主可控

## 快速开始

### 环境要求

- Python 3.10+
- (可选) Ollama — 如果需要使用本地模型

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
| POST | `/api/ingest/git` | 采集已配置仓库的 Git 提交记录 |
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

1. 选择一种方式导入活动数据（推荐直接用 Chrome、Google Calendar 或手动输入）
2. 对指定日期运行 AI 意图分析
3. 生成每日总结（自动提取知识图谱）
4. 查看知识图谱中的实体和关系
5. 基于总结生成明日计划和优化建议

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
