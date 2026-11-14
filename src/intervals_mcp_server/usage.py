"""Usage log: which athlete called which tool, and when.

Kept so one athlete can't quietly hog the server: if someone abuses it, the
log shows who, and the allowlist cuts them off.

Each tool call appends "HH:MM:SS tool" (UTC) to a Redis list keyed by athlete
and day, ``usage:<athlete_id>:<YYYY-MM-DD>``. Each day's list expires
RETENTION after that day starts, so nothing is kept longer than five weeks.
Only the athlete ID, the time and the tool name are stored — never tool
arguments, credentials or training data.

Storage is Upstash Redis through its REST API (KV_REST_API_URL and
KV_REST_API_TOKEN, set by the Vercel Marketplace integration). Without them,
nothing is recorded. A failure to record is logged and never fails the call.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger("intervals_mcp_server.usage")

RETENTION = timedelta(days=35)
TIMEOUT_SECONDS = 2.0
MAX_TOOL_NAME = 64


def _config() -> tuple[str, str] | None:
    url = os.getenv("KV_REST_API_URL")
    token = os.getenv("KV_REST_API_TOKEN")
    return (url.rstrip("/"), token) if url and token else None


def day_key(athlete_id: str, day: str) -> str:
    return f"usage:{athlete_id}:{day}"


def commands(athlete_id: str, tool: str, now: datetime) -> list[list[str]]:
    """The Redis commands that record one call made at ``now`` (UTC)."""
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    key = day_key(athlete_id, day_start.strftime("%Y-%m-%d"))
    entry = f"{now:%H:%M:%S} {tool[:MAX_TOOL_NAME]}"
    expire_at = int((day_start + RETENTION).timestamp())
    return [["RPUSH", key, entry], ["EXPIREAT", key, str(expire_at)]]


async def record(client: httpx.AsyncClient, athlete_id: str | None, tool: str) -> None:
    """Append one tool call to the usage log. Never raises."""
    config = _config()
    if not config or not athlete_id:
        return
    url, token = config
    try:
        response = await client.post(
            f"{url}/pipeline",
            json=commands(athlete_id, tool, datetime.now(timezone.utc)),
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        # The pipeline answers 200 even when a command fails; check each one.
        errors = [r["error"] for r in response.json() if isinstance(r, dict) and "error" in r]
        if errors:
            raise RuntimeError(errors)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("usage not recorded: athlete=%s tool=%s error=%r", athlete_id, tool, exc)
