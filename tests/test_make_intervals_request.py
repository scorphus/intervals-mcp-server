"""
Unit tests for the make_intervals_request function in intervals_mcp_server.server.

These tests focus on error handling, particularly the scenario where the API returns invalid JSON.
Mock classes are used to simulate httpx responses and client behavior.
"""

import asyncio
import logging
import os
import pathlib
import sys
from json import JSONDecodeError
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("API_KEY", "test")
os.environ.setdefault("ATHLETE_ID", "i1")

from intervals_mcp_server import server  # pylint: disable=wrong-import-position


def _make_bad_json_client():
    response = MagicMock()
    response.content = b"bad"
    response.status_code = 200
    response.raise_for_status = MagicMock()
    response.json.side_effect = JSONDecodeError("Expecting value", "bad", 0)
    client = MagicMock()
    client.is_closed = False
    client.request = AsyncMock(return_value=response)
    return client


def test_make_intervals_request_bad_json(monkeypatch, caplog):
    monkeypatch.setattr(server, "httpx_client", _make_bad_json_client())

    with caplog.at_level(logging.ERROR):
        result = asyncio.run(server.make_intervals_request("/bad", api_key="test"))

    assert result["error"] is True
    assert "Invalid JSON in response" in result["message"]
