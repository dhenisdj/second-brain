import json


def build_analysis_prompt(events) -> str:
    events_list = []
    for i, e in enumerate(events):
        events_list.append({
            "index": i,
            "timestamp": e.timestamp.isoformat(),
            "title": e.title,
            "content": e.content or "",
            "url": e.url or "",
            "duration_minutes": e.duration_minutes,
        })

    return f"""Analyze the following activity events and classify each one.

For each event, determine:
1. category: one of "work", "study", "life", "entertainment"
2. intent: a brief description of what the user was doing and why (in Chinese)
3. tags: relevant topic/project tags (in Chinese)
4. confidence: your confidence score from 0 to 1

Events:
{json.dumps(events_list, ensure_ascii=False, indent=2)}

Return JSON in this exact format:
{{
  "events": [
    {{
      "event_index": 0,
      "category": "work",
      "intent": "...",
      "tags": ["tag1", "tag2"],
      "confidence": 0.9
    }}
  ]
}}"""
