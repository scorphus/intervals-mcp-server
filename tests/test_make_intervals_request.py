import asyncio
import logging

import httpx

from intervals_mcp_server.server import make_intervals_request


class MockBadJSONResponse:
    def __init__(self):
        self.content = b"bad"
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        raise ValueError("No JSON")


class MockAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def get(self, *args, **kwargs):
        return MockBadJSONResponse()


def test_make_intervals_request_bad_json(monkeypatch, caplog):
    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    with caplog.at_level(logging.ERROR):
        result = asyncio.run(make_intervals_request("/bad"))

    assert result["error"] is True
    assert "Invalid JSON in response" in result["message"]
    assert "JSON decode error" in caplog.text
