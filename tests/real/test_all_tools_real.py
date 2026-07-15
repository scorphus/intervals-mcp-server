"""
Manual test script for all new MCP tools using real API credentials.

Run individual tests with pytest to save JSON output to tests/real/output/:
    ACTIVITY_ID=i12345 uv run pytest tests/real/test_all_tools_real.py -k test_get_power_curves
"""
import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

pytestmark = pytest.mark.asyncio
load_dotenv()

import sys
sys.path.insert(0, 'src')

from intervals_mcp_server.server import (
    list_events,
    get_power_curves,
    get_activity_power_curves,
    get_pace_curves,
    get_activity_pace_curve,
    get_power_hr_curve,
    get_activity_power_vs_hr,
    get_activity_hr_curve,
)

OUTPUT_DIR = Path(__file__).parent / "output"


def _save(name, result):
    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / f"{name}.json").write_text(json.dumps(result, indent=2, default=str))


async def test_list_events():
    result = await list_events(athlete_id=os.getenv('ATHLETE_ID'), limit=5)
    _save("list_events", result)


async def test_get_power_curves():
    result = await get_power_curves(
        athlete_id=os.getenv('ATHLETE_ID'), curves="42d", type_="Ride",
    )
    _save("get_power_curves", result)


async def test_get_activity_power_curves():
    activity_id = os.getenv('ACTIVITY_ID')
    if not activity_id:
        pytest.skip("ACTIVITY_ID not set")
    result = await get_activity_power_curves(activity_id)
    _save("get_activity_power_curves", result)


async def test_get_pace_curves():
    result = await get_pace_curves(
        athlete_id=os.getenv('ATHLETE_ID'), curves="42d", type_="Run",
    )
    _save("get_pace_curves", result)


async def test_get_activity_pace_curve():
    activity_id = os.getenv('ACTIVITY_ID')
    if not activity_id:
        pytest.skip("ACTIVITY_ID not set")
    result = await get_activity_pace_curve(activity_id)
    _save("get_activity_pace_curve", result)


async def test_get_power_hr_curve():
    result = await get_power_hr_curve(
        athlete_id=os.getenv('ATHLETE_ID'),
        start_date="2025-09-01",
        end_date="2025-10-03",
    )
    _save("get_power_hr_curve", result)


async def test_get_activity_power_vs_hr():
    activity_id = os.getenv('ACTIVITY_ID')
    if not activity_id:
        pytest.skip("ACTIVITY_ID not set")
    result = await get_activity_power_vs_hr(activity_id)
    _save("get_activity_power_vs_hr", result)


async def test_get_activity_hr_curve():
    activity_id = os.getenv('ACTIVITY_ID')
    if not activity_id:
        pytest.skip("ACTIVITY_ID not set")
    result = await get_activity_hr_curve(activity_id)
    _save("get_activity_hr_curve", result)
