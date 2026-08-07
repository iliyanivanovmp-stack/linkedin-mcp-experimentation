import asyncio

import pytest

from linkedin_mcp_client import LinkedInMCPClient, LinkedInMCPExtractor


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
