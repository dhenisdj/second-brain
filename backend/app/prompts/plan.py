import json


def build_plan_prompt(summary_data: dict) -> str:
    return f"""Based on the following daily summary, generate an actionable plan for tomorrow and optimization suggestions.

Today's summary:
{json.dumps(summary_data, ensure_ascii=False, indent=2)}

Generate:
1. items: prioritized action items for tomorrow
2. suggestions: attention/time optimization and learning review suggestions

Return JSON:
{{
  "items": [
    {{
      "title": "task title",
      "priority": "high|medium|low",
      "reason": "why this matters",
      "status": "todo",
      "estimated_minutes": 60,
      "scheduled_slot": "09:30-10:30"
    }}
  ],
  "suggestions": [
    {{"type": "attention|review|health|goal", "content": "suggestion text"}}
  ]
}}"""
