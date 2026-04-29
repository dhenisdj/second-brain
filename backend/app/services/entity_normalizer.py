import json
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover - optional dependency fallback
    fuzz = None


ALLOWED_NODE_TYPES = {"project", "person", "concept", "tool", "topic"}
SELF_CANONICAL_NAME = "我"
FUZZY_ACCEPT_THRESHOLD = 94.0
FUZZY_REVIEW_THRESHOLD = 88.0

SELF_ALIASES = {
    "i",
    "me",
    "myself",
    "self",
    "user",
    "current user",
    "end user",
    "the user",
    "我",
    "本人",
    "自己",
    "用户本人",
    "当前用户",
    "使用者",
    "操作者",
}

GENERIC_USER_TERMS = {
    "user",
    "users",
    "end user",
    "end users",
    "the user",
    "用户",
    "使用者",
    "用户群体",
}

GENERIC_PERSON_ROLE_TERMS = {
    "employee",
    "employees",
    "staff",
    "member",
    "members",
    "worker",
    "workers",
    "员工",
    "同事",
    "成员",
    "团队成员",
    "负责人",
    "申请人",
    "审批人",
    "管理员",
}

TYPE_PRIORITY = {
    "project": 5,
    "tool": 4,
    "person": 3,
    "topic": 2,
    "concept": 1,
}


@dataclass(frozen=True)
class EntityCandidate:
    name: str
    type: str
    aliases: tuple[str, ...]
    source: str


@dataclass(frozen=True)
class CandidateMatch:
    candidate: EntityCandidate
    score: float
    method: str


class EntityResolutionIndex:
    def __init__(self, existing_nodes: list[dict[str, Any]] | None = None):
        self._candidates: list[EntityCandidate] = []
        self._alias_to_candidate: dict[str, EntityCandidate] = {}
        for node in existing_nodes or []:
            self.add_candidate(
                name=node.get("name"),
                node_type=node.get("type"),
                aliases=_aliases_from_properties(node.get("properties")),
                source="existing",
            )

    def add_candidate(
        self,
        *,
        name: Any,
        node_type: Any,
        aliases: list[str] | tuple[str, ...] | set[str] | None = None,
        source: str = "batch",
    ) -> None:
        canonical_name = _compact_text(name)
        if not canonical_name:
            return

        candidate = EntityCandidate(
            name=canonical_name,
            type=_safe_type(node_type),
            aliases=tuple(sorted({_compact_text(alias) for alias in (aliases or []) if _compact_text(alias)})),
            source=source,
        )
        self._candidates.append(candidate)
        for alias in (canonical_name, *candidate.aliases):
            self._alias_to_candidate.setdefault(_match_key(alias), candidate)

    def find(self, name: str, node_type: str) -> CandidateMatch | None:
        exact = self._alias_to_candidate.get(_match_key(name))
        if exact and _types_compatible(exact.type, node_type):
            return CandidateMatch(candidate=exact, score=100.0, method="exact_alias")

        best: CandidateMatch | None = None
        name_key = _fuzzy_key(name)
        if not name_key:
            return None

        for candidate in self._candidates:
            if not _types_compatible(candidate.type, node_type):
                continue
            for alias in (candidate.name, *candidate.aliases):
                score = _fuzzy_score(name_key, _fuzzy_key(alias))
                if not best or score > best.score:
                    best = CandidateMatch(candidate=candidate, score=score, method=_fuzzy_method())

        return best


def _compact_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.strip().strip("\"'`“”‘’")
    return re.sub(r"\s+", " ", text)


def _match_key(value: Any) -> str:
    return _compact_text(value).casefold()


def _fuzzy_key(value: Any) -> str:
    key = _match_key(value)
    key = re.sub(r"[_\-./:]+", " ", key)
    return re.sub(r"\s+", " ", key).strip()


def _safe_type(value: Any) -> str:
    node_type = _match_key(value)
    return node_type if node_type in ALLOWED_NODE_TYPES else "concept"


def _prefer_type(left: str, right: str) -> str:
    return left if TYPE_PRIORITY.get(left, 0) >= TYPE_PRIORITY.get(right, 0) else right


def _types_compatible(left: str, right: str) -> bool:
    if left == right:
        return True
    return {left, right} <= {"concept", "topic"}


def _fuzzy_score(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if fuzz is not None:
        return float(max(fuzz.WRatio(left, right), fuzz.token_sort_ratio(left, right)))
    return SequenceMatcher(None, left, right).ratio() * 100


def _fuzzy_method() -> str:
    return "rapidfuzz" if fuzz is not None else "difflib"


def _parse_properties(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _aliases_from_properties(value: Any) -> list[str]:
    properties = _parse_properties(value)
    aliases: list[str] = []
    raw_aliases = properties.get("aliases")
    if isinstance(raw_aliases, list):
        aliases.extend(str(alias) for alias in raw_aliases)
    elif isinstance(raw_aliases, str):
        aliases.append(raw_aliases)

    normalized_from = properties.get("normalized_from")
    if isinstance(normalized_from, list):
        aliases.extend(str(alias) for alias in normalized_from)
    elif isinstance(normalized_from, str):
        aliases.append(normalized_from)

    return aliases


def _merge_aliases(properties: dict[str, Any], aliases: set[str]) -> dict[str, Any]:
    existing_aliases = set(_aliases_from_properties(properties))
    merged_aliases = sorted(alias for alias in existing_aliases | aliases if alias)
    if merged_aliases:
        properties["aliases"] = merged_aliases
    return properties


def _with_resolution_properties(
    properties: dict[str, Any],
    *,
    canonical_name: str,
    original_name: str,
    original_type: str,
    canonical_type: str,
    method: str,
    confidence: float,
    candidate_match: CandidateMatch | None = None,
) -> dict[str, Any]:
    aliases = {original_name}
    if candidate_match:
        aliases.update(candidate_match.candidate.aliases)
    properties = {
        **properties,
        "canonical_name": canonical_name,
        "resolution_method": method,
        "resolution_confidence": round(confidence, 4),
    }

    if canonical_name != original_name:
        properties["normalized_from"] = original_name
    if canonical_type != original_type:
        properties["original_type"] = original_type

    if candidate_match and candidate_match.score >= FUZZY_REVIEW_THRESHOLD:
        properties["resolution_candidates"] = [
            {
                "name": candidate_match.candidate.name,
                "type": candidate_match.candidate.type,
                "score": round(candidate_match.score / 100, 4),
                "method": candidate_match.method,
            }
        ]

    return _merge_aliases(properties, aliases)


def normalize_node_data(
    node_data: dict[str, Any],
    resolution_index: EntityResolutionIndex | None = None,
) -> dict[str, Any] | None:
    """Normalize one extracted entity before it is written to the local graph."""
    original_name = _compact_text(node_data.get("name"))
    if not original_name:
        return None

    original_type = _safe_type(node_data.get("type", "concept"))
    key = _match_key(original_name)

    canonical_name = original_name
    canonical_type = original_type
    method = "identity"
    confidence = 1.0
    candidate_match: CandidateMatch | None = None

    if key in SELF_ALIASES or (original_type == "person" and key in GENERIC_USER_TERMS):
        canonical_name = SELF_CANONICAL_NAME
        canonical_type = "person"
        method = "rule:self_alias"
    elif key in GENERIC_USER_TERMS:
        canonical_name = "用户群体"
        canonical_type = "topic"
        method = "rule:generic_user"
    elif key in GENERIC_PERSON_ROLE_TERMS:
        canonical_name = original_name
        canonical_type = "topic"
        method = "rule:generic_role"
    elif resolution_index:
        candidate_match = resolution_index.find(original_name, original_type)
        if candidate_match and candidate_match.score >= FUZZY_ACCEPT_THRESHOLD:
            canonical_name = candidate_match.candidate.name
            canonical_type = candidate_match.candidate.type
            method = candidate_match.method
            confidence = candidate_match.score / 100

    properties = node_data.get("properties") if isinstance(node_data.get("properties"), dict) else {}
    properties = _with_resolution_properties(
        properties,
        canonical_name=canonical_name,
        original_name=original_name,
        original_type=original_type,
        canonical_type=canonical_type,
        method=method,
        confidence=confidence,
        candidate_match=candidate_match,
    )

    return {
        "name": canonical_name,
        "type": canonical_type,
        "properties": properties,
    }


def normalize_graph_data(
    graph_data: dict[str, Any],
    existing_nodes: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Canonicalize entity names/types and rewrite edges to canonical endpoints."""
    resolution_index = EntityResolutionIndex(existing_nodes)
    original_to_canonical: dict[str, str] = {}
    nodes_by_name: dict[str, dict[str, Any]] = {}

    for raw_node in graph_data.get("nodes") or []:
        if not isinstance(raw_node, dict):
            continue
        normalized = normalize_node_data(raw_node, resolution_index)
        original_name = _compact_text(raw_node.get("name"))
        if not normalized or not original_name:
            continue

        original_to_canonical[original_name] = normalized["name"]
        original_to_canonical[_match_key(original_name)] = normalized["name"]

        existing = nodes_by_name.get(normalized["name"])
        if existing:
            existing["type"] = _prefer_type(existing["type"], normalized["type"])
            existing["properties"] = merge_properties(existing.get("properties"), normalized.get("properties"))
            continue

        nodes_by_name[normalized["name"]] = normalized
        resolution_index.add_candidate(
            name=normalized["name"],
            node_type=normalized["type"],
            aliases=_aliases_from_properties(normalized.get("properties")),
            source="batch",
        )

    normalized_edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str]] = set()

    for raw_edge in graph_data.get("edges") or []:
        if not isinstance(raw_edge, dict):
            continue

        source = _canonical_endpoint(raw_edge.get("source"), original_to_canonical)
        target = _canonical_endpoint(raw_edge.get("target"), original_to_canonical)
        relation = _compact_text(raw_edge.get("relation")) or "related_to"

        if not source or not target or source == target:
            continue
        if source not in nodes_by_name or target not in nodes_by_name:
            continue

        key = (source, target, relation)
        if key in seen_edges:
            continue
        seen_edges.add(key)

        edge = {
            "source": source,
            "target": target,
            "relation": relation,
        }
        if raw_edge.get("context"):
            edge["context"] = raw_edge["context"]
        normalized_edges.append(edge)

    return {
        "nodes": list(nodes_by_name.values()),
        "edges": normalized_edges,
    }


def merge_properties(existing: Any, incoming: Any) -> dict[str, Any]:
    existing_properties = _parse_properties(existing)
    incoming_properties = _parse_properties(incoming)
    aliases = set(_aliases_from_properties(existing_properties)) | set(_aliases_from_properties(incoming_properties))
    merged = {
        **existing_properties,
        **incoming_properties,
    }
    return _merge_aliases(merged, aliases)


def _canonical_endpoint(value: Any, original_to_canonical: dict[str, str]) -> str | None:
    name = _compact_text(value)
    if not name:
        return None
    return original_to_canonical.get(name) or original_to_canonical.get(_match_key(name))
