import asyncio

import pytest

from linkedin_mcp_client import (
    LinkedInMCPClient,
    LinkedInMCPExtractor,
    LinkedInMCPSessionError,
)


def test_client_requires_auth_token(monkeypatch):
    monkeypatch.delenv("LINKEDIN_MCP_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="LINKEDIN_MCP_TOKEN"):
        LinkedInMCPClient()


def test_content_text_extracts_mcp_text_blocks():
    result = {"content": [{"type": "text", "text": '{"job_ids": ["123"]}'}]}
    assert LinkedInMCPClient._content_text(result) == '{"job_ids": ["123"]}'


def test_extractor_routes_search_through_official_mcp_tool():
    calls = []

    class FakeClient:
        def call_tool(self, name, arguments):
            calls.append((name, arguments))
            return {"job_ids": ["123"]}

    result = asyncio.run(
        LinkedInMCPExtractor(FakeClient()).search_jobs(
            "revenue operations", location="United States", max_pages=1
        )
    )

    assert result == {"job_ids": ["123"]}
    assert calls == [(
        "search_jobs",
        {"keywords": "revenue operations", "location": "United States", "max_pages": 1},
    )]


def test_session_error_is_actionable(monkeypatch):
    monkeypatch.setenv("LINKEDIN_MCP_TOKEN", "token")

    class FakeResponse:
        headers = {}

        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    responses = [
        FakeResponse(b'{"result": {}}'),
        FakeResponse(b""),
        FakeResponse(
            b'{"result": {"isError": true, "content": [{"type": "text", "text": '
            b'"No valid LinkedIn session is available in Docker. Run --login on the host machine to create a session, then retry this tool."}]}}'
        ),
    ]

    def fake_urlopen(request, timeout):
        return responses.pop(0)

    monkeypatch.setattr("linkedin_mcp_client.urllib.request.urlopen", fake_urlopen)

    client = LinkedInMCPClient()
    with pytest.raises(LinkedInMCPSessionError, match="linkedin-mcp-vol"):
        client.call_tool("search_jobs", {"keywords": "revops"})
