import json


def build_summary_prompt(daily_digest: dict) -> str:
    return f"""Based on the following compact daily activity digest, generate a comprehensive daily summary.

The digest was created by a pre-summary content extractor. It already groups high-volume raw events into major topics, timeline blocks, source summaries, and short evidence snippets. Prefer the digest conclusions over individual evidence snippets, and do not invent details that are not supported by the digest.

Daily digest:
{json.dumps(daily_digest, ensure_ascii=False, indent=2)}

Generate a JSON response with:
1. timeline_md: A markdown timeline of the day's activities (in Chinese)
2. progress_md: A markdown summary of project/task progress (in Chinese)
3. knowledge_md: A markdown summary of new knowledge learned (in Chinese)
4. time_distribution: An object with category percentages that sum to 100

Guidelines:
- Use main_topics and source_summaries to identify the day's important work.
- Use timeline_blocks for chronology; keep the final timeline concise.
- Use category_distribution_estimate as a starting point for time_distribution and adjust only when evidence strongly suggests it.
- Mention uncertainty briefly when the digest only contains weak evidence.

Return JSON in this exact format:
{{
  "timeline_md": "## 时间线\\n- 09:00 ...",
  "progress_md": "## 事项进展\\n### ...",
  "knowledge_md": "## 新知识\\n- ...",
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
