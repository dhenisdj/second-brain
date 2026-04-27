# Changelog

All notable changes to this project will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/).

## [0.1.0] - 2026-04-03

### Added
- 数据导入方式：Chrome 浏览历史 JSON 上传、浏览器本地采集、Google Calendar 采集、手动输入活动记录（AC-1）
- AI 意图理解：自动推断活动类别（工作/学习/生活/娱乐）、意图和主题标签（AC-2）
- 每日总结生成：时间线动线、事项进展、新知识提取、时间分布统计（AC-3）
- 轻量知识图谱：基于 SQLite 的增量式知识图谱，自动提取实体和关系（AC-4）
- 计划与建议：AI 生成带优先级的明日计划和注意力/学习优化建议，可编辑（AC-5）
- LLM 双模式支持：OpenAI API 和 Ollama 本地模型配置切换（AC-6）
- 数据管理：按日期浏览数据概览，支持单条和整天数据物理删除（AC-7）
- 后端 API：FastAPI + SQLAlchemy + SQLite，16 个 RESTful 接口
- 测试覆盖：53 个单元测试 + 8 个 E2E 测试场景，通过率 100%
