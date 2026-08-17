"""Client adapter for the centralized LinkedIn MCP service."""

from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Any


DEFAULT_ENDPOINT = (
    "https://iliyan-ivanov-mp--linkedin-mcp-linkedin-mcp-server.modal.run/mcp"
)

SESSION_ERROR_MARKERS = (
    "no valid linkedin session",
    "run --login",
    "create a session",
    "not logged in",
    "cookies",
)


class LinkedInMCPSessionError(RuntimeError):
    """Raised when the centralized MCP is reachable but unauthenticated."""


def is_session_error(message: str) -> bool:
    text = message.casefold()
    return "linkedin" in text and any(marker in text for marker in SESSION_ERROR_MARKERS)


def session_error_message(detail: str) -> str:
    return (
        "Central LinkedIn MCP session is not valid. Refresh the shared "
        "`linkedin-mcp-vol` session from the host before enabling sourcing: "
        "`uvx mcp-server-linkedin@latest --login`, then upload "
        "`~/.linkedin-mcp/cookies.json`, `source-state.json`, "
        "`browser-install.json`, and `profile` to `linkedin-mcp-vol`. "
        f"MCP detail: {detail}"
    )


class LinkedInMCPClient:
    def __init__(self, endpoint: str | None = None) -> None:
        self.endpoint = (endpoint or os.environ.get("LINKEDIN_MCP_URL") or DEFAULT_ENDPOINT).strip()
        self.auth_token = os.environ.get("LINKEDIN_MCP_TOKEN", "").strip()
        if not self.auth_token:
            raise RuntimeError("LINKEDIN_MCP_TOKEN is not configured")
        self.session_id = ""
        self.request_id = 0
        self.last_call_at = 0.0
        self.delay_seconds = float(os.environ.get("LINKEDIN_MCP_CALL_DELAY_SECONDS", "10"))
        self._initialize()

    def _post(self, payload: dict[str, Any], *, expect_response: bool = True) -> dict[str, Any] | None:
        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=240) as response:
            body = response.read().decode("utf-8", "ignore")
            self.session_id = response.headers.get("Mcp-Session-Id") or self.session_id
        if not expect_response:
            return None
        messages = [
            json.loads(line[6:])
            for line in body.splitlines()
            if line.startswith("data: ")
        ]
        if not messages and body.strip():
            messages = [json.loads(body)]
        if not messages:
            raise RuntimeError("LinkedIn MCP returned an empty response")
        message = messages[-1]
        if "error" in message:
            raise RuntimeError(f"LinkedIn MCP error: {message['error']}")
        return message

    def _initialize(self) -> None:
        self.request_id += 1
        self._post({
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "signal-platform", "version": "1.0"},
            },
            "id": self.request_id,
        })
        self._post(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            expect_response=False,
        )

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        elapsed = time.monotonic() - self.last_call_at
        if self.last_call_at and elapsed < self.delay_seconds:
            time.sleep(self.delay_seconds - elapsed)
        self.request_id += 1
        message = self._post({
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
            "id": self.request_id,
        })
        self.last_call_at = time.monotonic()
        result = (message or {}).get("result", {})
        if result.get("isError"):
            text = self._content_text(result) or f"LinkedIn MCP tool {name} failed"
            if is_session_error(text):
                raise LinkedInMCPSessionError(session_error_message(text))
            raise RuntimeError(text)
        text = self._content_text(result)
        if not text:
            return {}
        parsed = self._parse_tool_payload(text, name)
        if not isinstance(parsed, dict):
            raise RuntimeError(f"LinkedIn MCP tool {name} returned a non-object result")
        return parsed

    @staticmethod
    def _content_text(result: dict[str, Any]) -> str:
        return "\n".join(
            str(item.get("text", ""))
            for item in result.get("content", [])
            if isinstance(item, dict) and item.get("type") == "text"
        ).strip()

    @staticmethod
    def _parse_tool_payload(text: str, name: str) -> Any:
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            decoder = json.JSONDecoder()
            stripped = text.lstrip()
            try:
                parsed, _ = decoder.raw_decode(stripped)
            except json.JSONDecodeError:
                raise RuntimeError(f"LinkedIn MCP tool {name} returned invalid JSON") from error
            return parsed

    def close(self) -> None:
        try:
            self.call_tool("close_session", {})
        except Exception:
            pass


class LinkedInMCPExtractor:
    """Expose the local extractor interface through centralized MCP tools."""

    def __init__(self, client: LinkedInMCPClient) -> None:
        self.client = client

    async def search_jobs(self, keywords: str, **filters: Any) -> dict[str, Any]:
        arguments = {"keywords": keywords}
        arguments.update({key: value for key, value in filters.items() if value is not None})
        return self.client.call_tool("search_jobs", arguments)

    async def scrape_job(self, job_id: str) -> dict[str, Any]:
        return self.client.call_tool("get_job_details", {"job_id": str(job_id)})

    async def scrape_company(self, company_name: str, sections: set[str] | None = None) -> dict[str, Any]:
        extras = sorted(set(sections or set()) - {"about"})
        arguments: dict[str, Any] = {"company_name": company_name}
        if extras:
            arguments["sections"] = ",".join(extras)
        return self.client.call_tool("get_company_profile", arguments)
