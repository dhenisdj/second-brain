from collections import Counter
from typing import Callable

from app.services.chrome_collector import collect_chrome_history
from app.services.safari_collector import collect_safari_history

BROWSER_SOURCES = ("chrome", "safari")


def is_browser_source(source: str | None) -> bool:
    return source in BROWSER_SOURCES


def _date_range_from_events(events: list[dict]) -> list[str]:
    if not events:
        return []
    dates = sorted({event["visit_time"][:10] for event in events})
    return [dates[0], dates[-1]] if dates else []


def collect_browser_history(days: int = 2) -> dict:
    """Collect local browsing history across supported browsers."""
    collectors: list[tuple[str, Callable[[int], dict]]] = [
        ("chrome", collect_chrome_history),
        ("safari", collect_safari_history),
    ]

    events: list[dict] = []
    warnings: list[str] = []
    collected_sources: list[str] = []
    errors: list[tuple[str, str]] = []

    for source, collector in collectors:
        try:
            result = collector(days)
        except FileNotFoundError as exc:
            errors.append(("not_found", str(exc)))
            continue
        except PermissionError as exc:
            warnings.append(str(exc))
            errors.append(("permission", str(exc)))
            continue
        except Exception as exc:
            message = f"{source.capitalize()} 历史记录采集失败：{exc}"
            warnings.append(message)
            errors.append(("error", message))
            continue

        collected_sources.append(source)
        events.extend(result.get("events", []))

    events.sort(key=lambda event: event["visit_time"])

    if not collected_sources:
        if any(kind == "permission" for kind, _ in errors):
            raise PermissionError("浏览器历史访问被系统拒绝。请为当前终端或 Python 解释器授予“完全磁盘访问权限”。")
        raise FileNotFoundError("未找到可读取的浏览器历史数据库。已检查 Chrome 和 Safari。")

    source_breakdown = dict(Counter(event.get("source", "unknown") for event in events))

    return {
        "events": events,
        "total": len(events),
        "date_range": _date_range_from_events(events),
        "collected_sources": collected_sources,
        "source_breakdown": source_breakdown,
        "warnings": warnings,
    }
