import asyncio
import logging
from json import JSONDecodeError
import os

os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("ATHLETE_ID", "i123456")

import intervals_mcp_server.server as server


class MockBadJSONResponse:
    def __init__(self):
        self.content = b"bad"
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        raise JSONDecodeError("Expecting value", "bad", 0)


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
    monkeypatch.setattr(server, "httpx_client", MockAsyncClient())

    with caplog.at_level(logging.ERROR):
        result = asyncio.run(server.make_intervals_request("/bad"))

    assert result["error"] is True
    assert "Invalid JSON in response" in result["message"]
