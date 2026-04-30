import json


def build_summary_prompt(daily_digest: dict) -> str:
    return f"""Based on the following compact daily activity digest, generate a comprehensive daily summary.

The digest was created by a pre-summary content extractor. It already groups high-volume raw events into major topics, timeline blocks, source summaries, and short evidence snippets. Prefer the digest conclusions over individual evidence snippets, and do not invent details that are not supported by the digest.

Daily digest:
{json.dumps(daily_digest, ensure_ascii=False, indent=2)}

Generate a JSON response with both structured fields for UI rendering and markdown fallbacks:
1. timeline: array of chronological time blocks. Each item has time, title, summary, category, and items.
2. progress: array grouped by project/topic. Each item has project, progress, issues, risks, and next_steps arrays.
3. knowledge: array grouped by knowledge topic. Each item has topic, summary, takeaways, and evidence.
4. timeline_md, progress_md, knowledge_md: markdown fallbacks in Chinese.
5. time_distribution: An object with category percentages that sum to 100.

Guidelines:
- Use main_topics and source_summaries to identify the day's important work.
- Use timeline_blocks for chronology; keep the final timeline concise.
- Use category_distribution_estimate as a starting point for time_distribution and adjust only when evidence strongly suggests it.
- Mention uncertainty briefly when the digest only contains weak evidence.
- Avoid duplicated section headings. Do not start timeline_md with "## 时间线", progress_md with "## 事项进展", or knowledge_md with "## 新知识".
- For progress, use project/topic as level-1 grouping and classify details into progress, issues, risks, and next_steps. Use empty arrays when a class has no evidence.
- For knowledge, group by concrete concepts/tools/decisions. Do not make a generic "新知识" item.
- Keep each bullet concise and evidence-backed. Do not invent project names that are not implied by the digest.

Return JSON in this exact format:
{{
  "timeline": [
    {{"time": "09:00", "title": "站会与计划同步", "summary": "围绕 Q2 OKR 对齐任务分工。", "category": "work", "items": ["确认数据分析负责人", "补充后续跟进点"]}}
  ],
  "progress": [
    {{"project": "Q2 OKR", "progress": ["完成数据分析任务分工"], "issues": [], "risks": ["依赖数据口径确认"], "next_steps": ["补齐指标定义"]}}
  ],
  "knowledge": [
    {{"topic": "Self-Attention", "summary": "通过 Q/K/V 计算 token 间依赖权重。", "takeaways": ["多头注意力可并行捕捉不同子空间特征"], "evidence": "论文阅读记录"}}
  ],
  "timeline_md": "- 09:00 站会与计划同步：围绕 Q2 OKR 对齐任务分工。",
  "progress_md": "### Q2 OKR\\n#### 进展\\n- 完成数据分析任务分工\\n#### 风险\\n- 依赖数据口径确认",
  "knowledge_md": "### Self-Attention\\n- 通过 Q/K/V 计算 token 间依赖权重。",
  "time_distribution": {{"work": 50, "study": 30, "life": 15, "entertainment": 5}}
}}"""


def build_graph_extraction_prompt(summary_data: dict) -> str:
    return f"""Extract key entities and their relationships from the following daily summary.

Summary:
{json.dumps(summary_data, ensure_ascii=False, indent=2)}

Identify entities of types: project, person, concept, tool, topic
Identify relationships: uses, belongs_to, related_to, learned

Entity normalization rules:
- Do not create separate person nodes for pronouns or generic self references.
- If the summary refers to the current user as "我", "本人", "用户", "User", or "current user", use exactly one person node named "我".
- Generic roles such as "员工", "同事", "成员", "申请人", "审批人", or "管理员" are not specific people. Use topic/concept only when the role itself is important.
- Use stable product/project/tool names. Keep capitalization for real names, but do not create duplicate aliases for the same entity.

Return JSON:
{{
  "nodes": [
    {{"name": "entity name", "type": "concept"}}
  ],
  "edges": [
    {{"source": "entity1", "target": "entity2", "relation": "related_to"}}
  ]
}}"""
