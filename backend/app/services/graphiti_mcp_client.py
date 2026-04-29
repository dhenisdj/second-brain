import json
from typing import Any
from urllib.parse import urlparse

import httpx


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class GraphitiMCPError(RuntimeError):
    """Raised when the Graphiti MCP server cannot be reached or returns an error."""


def _parse_mcp_response(raw: str) -> dict[str, Any]:
    stripped = raw.strip()
    if not stripped:
        return {}

    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise GraphitiMCPError("Graphiti MCP returned invalid JSON.") from exc
        if not isinstance(parsed, dict):
            raise GraphitiMCPError("Graphiti MCP returned an unexpected JSON payload.")
        return parsed

    data_lines = []
    for line in stripped.splitlines():
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())

    if not data_lines:
        raise GraphitiMCPError("Graphiti MCP returned an empty stream response.")

    try:
        parsed = json.loads("\n".join(data_lines))
    except json.JSONDecodeError as exc:
        raise GraphitiMCPError("Graphiti MCP returned an invalid event stream payload.") from exc
    if not isinstance(parsed, dict):
        raise GraphitiMCPError("Graphiti MCP returned an unexpected event stream payload.")
    return parsed


class GraphitiMCPClient:
    def __init__(
        self,
        endpoint: str,
        *,
        timeout_seconds: int = 60,
        allow_remote: bool = False,
    ):
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.allow_remote = allow_remote
        self.session_id: str | None = None
        self._next_id = 1

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    def _validate_endpoint(self) -> None:
        parsed = urlparse(self.endpoint)
        if parsed.scheme not in {"http", "https"}:
            raise GraphitiMCPError("Graphiti MCP URL must use HTTP or HTTPS.")
        if not self.allow_remote and parsed.hostname not in LOOPBACK_HOSTS:
            raise GraphitiMCPError("Graphiti MCP remote URLs are disabled by default.")

    def _request_id(self) -> int:
        value = self._next_id
        self._next_id += 1
        return value

    async def _post(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        self._validate_endpoint()
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.post(self.endpoint, json=payload, headers=headers)
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text.strip()
            raise GraphitiMCPError(
                f"Graphiti MCP request failed: {body or exc.response.reason_phrase}"
            ) from exc
        except httpx.HTTPError as exc:
            raise GraphitiMCPError(f"Cannot connect to Graphiti MCP at {self.endpoint}.") from exc

        return _parse_mcp_response(resp.text), resp.headers.get("mcp-session-id")

    async def initialize(self) -> None:
        response, session_id = await self._post(
            {
                "jsonrpc": "2.0",
                "id": self._request_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "second-brain", "version": "0.1.0"},
                },
            }
        )
        self._raise_for_jsonrpc_error(response)
        self.session_id = session_id or self.session_id
        await self._post(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            }
        )

    async def close(self) -> None:
        if not self.session_id:
            return
        headers = {"mcp-session-id": self.session_id}
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.delete(self.endpoint, headers=headers)
        except httpx.HTTPError:
            pass
        finally:
            self.session_id = None

    @staticmethod
    def _raise_for_jsonrpc_error(response: dict[str, Any]) -> None:
        if response.get("error"):
            raise GraphitiMCPError(f"Graphiti MCP error: {response['error']}")

    @staticmethod
    def _extract_tool_result(result: dict[str, Any], tool_name: str) -> dict[str, Any]:
        if result.get("isError"):
            content = result.get("content") or []
            message = None
            if content and isinstance(content[0], dict):
                message = content[0].get("text")
            raise GraphitiMCPError(message or f"Graphiti MCP tool {tool_name} failed.")

        if isinstance(result.get("structuredContent"), dict):
            return result["structuredContent"]

        content = result.get("content") or []
        texts = [
            str(item.get("text"))
            for item in content
            if isinstance(item, dict) and item.get("text") is not None
        ]
        if not texts:
            return result

        text = "\n".join(texts).strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}
        return parsed if isinstance(parsed, dict) else {"value": parsed}

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        response, _ = await self._post(
            {
                "jsonrpc": "2.0",
                "id": self._request_id(),
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }
        )
        self._raise_for_jsonrpc_error(response)
        result = response.get("result")
        if not isinstance(result, dict):
            raise GraphitiMCPError(f"Graphiti MCP tool {name} returned an invalid result.")
        return self._extract_tool_result(result, name)

    async def call_tool_with_fallback(
        self,
        names: tuple[str, ...],
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        last_error: GraphitiMCPError | None = None
        for name in names:
            try:
                return await self.call_tool(name, arguments)
            except GraphitiMCPError as exc:
                last_error = exc
                if "unknown tool" not in str(exc).lower() and "not found" not in str(exc).lower():
                    raise
        raise last_error or GraphitiMCPError("No Graphiti MCP tool names were provided.")

    async def add_memory(
        self,
        *,
        name: str,
        episode_body: str,
        group_id: str,
        source: str = "json",
        source_description: str = "",
        uuid: str | None = None,
    ) -> dict[str, Any]:
        args = {
            "name": name,
            "episode_body": episode_body,
            "group_id": group_id,
            "source": source,
            "source_description": source_description,
        }
        if uuid:
            args["uuid"] = uuid
        return await self.call_tool_with_fallback(("add_memory", "add_episode"), args)

    async def search_nodes(
        self,
        *,
        query: str,
        group_ids: list[str],
        max_nodes: int = 10,
    ) -> dict[str, Any]:
        return await self.call_tool(
            "search_nodes",
            {"query": query, "group_ids": group_ids, "max_nodes": max_nodes},
        )

    async def search_facts(
        self,
        *,
        query: str,
        group_ids: list[str],
        max_facts: int = 10,
    ) -> dict[str, Any]:
        return await self.call_tool_with_fallback(
            ("search_memory_facts", "search_facts"),
            {"query": query, "group_ids": group_ids, "max_facts": max_facts},
        )

    async def get_status(self) -> dict[str, Any]:
        return await self.call_tool("get_status", {})
