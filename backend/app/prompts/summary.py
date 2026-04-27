import json


def build_summary_prompt(events_data: list[dict]) -> str:
    return f"""Based on the following analyzed activity events for one day, generate a comprehensive daily summary.

Events:
{json.dumps(events_data, ensure_ascii=False, indent=2)}

Generate a JSON response with:
1. timeline_md: A markdown timeline of the day's activities (in Chinese)
2. progress_md: A markdown summary of project/task progress (in Chinese)
3. knowledge_md: A markdown summary of new knowledge learned (in Chinese)
4. time_distribution: An object with category percentages that sum to 100

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

Return JSON:
{{
  "nodes": [
    {{"name": "entity name", "type": "concept"}}
  ],
  "edges": [
    {{"source": "entity1", "target": "entity2", "relation": "related_to"}}
  ]
}}"""
