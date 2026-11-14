import asyncio
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import httpx  # noqa: E402

from intervals_mcp_server import usage  # noqa: E402


def test_commands_append_time_and_tool_to_the_days_list():
    now = datetime(2026, 11, 14, 14, 3, 22, tzinfo=timezone.utc)
    cmds = usage.commands("i12345", "get_activities", now)
    assert cmds[0] == ["RPUSH", "usage:i12345:2026-11-14", "14:03:22 get_activities"]


def test_commands_expire_the_day_five_weeks_after_it_starts():
    now = datetime(2026, 11, 14, 23, 59, 59, tzinfo=timezone.utc)
    cmds = usage.commands("i12345", "get_activities", now)
    expected = datetime(2026, 12, 19, tzinfo=timezone.utc).timestamp()
    assert cmds[1] == ["EXPIREAT", "usage:i12345:2026-11-14", str(int(expected))]


def test_commands_cap_tool_name_length():
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    entry = usage.commands("i1", "x" * 500, now)[0][2]
    assert entry == "00:00:00 " + "x" * usage.MAX_TOOL_NAME


def _record(monkeypatch, handler, athlete_id="i12345"):
    monkeypatch.setenv("KV_REST_API_URL", "https://kv.example/")
    monkeypatch.setenv("KV_REST_API_TOKEN", "t")
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(wrapped)) as client:
            await usage.record(client, athlete_id, "get_activities")

    asyncio.run(run())
    return seen


def test_record_posts_pipeline_with_token(monkeypatch):
    seen = _record(monkeypatch, lambda r: httpx.Response(200, json=[{"result": 1}, {"result": 1}]))
    assert len(seen) == 1
    assert str(seen[0].url) == "https://kv.example/pipeline"
    assert seen[0].headers["authorization"] == "Bearer t"
    assert b'"RPUSH"' in seen[0].content and b"get_activities" in seen[0].content


def test_record_skips_without_athlete(monkeypatch):
    seen = _record(monkeypatch, lambda r: httpx.Response(200, json=[]), athlete_id=None)
    assert seen == []


def test_record_skips_without_config(monkeypatch):
    monkeypatch.delenv("KV_REST_API_URL", raising=False)
    monkeypatch.delenv("KV_REST_API_TOKEN", raising=False)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: 1 / 0)) as client:
            await usage.record(client, "i12345", "get_activities")

    asyncio.run(run())


def test_record_never_raises(monkeypatch, caplog):
    def boom(request):
        raise httpx.ConnectError("down")

    _record(monkeypatch, boom)
    _record(monkeypatch, lambda r: httpx.Response(500))
    _record(monkeypatch, lambda r: httpx.Response(200, json=[{"error": "ERR"}, {"result": 1}]))
    assert caplog.text.count("usage not recorded") == 3


def test_server_records_each_tool_call(monkeypatch):
    from intervals_mcp_server import server

    calls = []

    async def fake_record(client, athlete_id, tool):
        calls.append((athlete_id, tool))

    monkeypatch.setattr(server.usage, "record", fake_record)
    monkeypatch.setattr(server, "_get_intervals_athlete_id", lambda: "i12345")
    asyncio.run(server.mcp.call_tool("get_current_date_and_time_info", {}))
    assert calls == [("i12345", "get_current_date_and_time_info")]
