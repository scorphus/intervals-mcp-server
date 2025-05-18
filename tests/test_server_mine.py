import json
import sys

# add src/intervals_mcp_server to the Python path:
sys.path.append("src/intervals_mcp_server")

import pytest
import server
from dotenv import load_dotenv


def test_server_exists():
    assert server is not None


@pytest.mark.asyncio
async def test_server_get_activities():
    env = load_dotenv()
    assert env is not None
    assert server.API_KEY is not None
    assert server.ATHLETE_ID is not None
    response = await server.get_activities(
        athlete_id=server.ATHLETE_ID,
        api_key=server.API_KEY,
        # start_date="2025-03-31",
        # end_date="2025-04-06",
        start_date="2025-04-08",
        end_date="2025-04-08",
        limit=20,
        include_unnamed=True,
    )
    print(response)
    # Save the response to activities.md
    with open("activities.md", "w") as f:
        f.write(response)


@pytest.mark.asyncio
async def test_server_get_races():
    env = load_dotenv()
    assert env is not None
    assert server.API_KEY is not None
    assert server.ATHLETE_ID is not None
    response = await server.get_races(
        athlete_id=server.ATHLETE_ID, api_key=server.API_KEY
    )
    print(response)
    # Save the response to activities.md
    with open("races.md", "w") as f:
        f.write(response)


@pytest.mark.asyncio
async def test_server_get_events():
    env = load_dotenv()
    assert env is not None
    assert server.API_KEY is not None
    assert server.ATHLETE_ID is not None
    response = await server.get_events(
        athlete_id=server.ATHLETE_ID,
        api_key=server.API_KEY,
        start_date="2025-04-01",
        end_date="2025-05-31",
    )
    print(response)
    # Save the response to activities.md
    with open("events.md", "w") as f:
        f.write(response)


@pytest.mark.asyncio
async def test_server_get_power_curves():
    env = load_dotenv()
    assert env is not None
    assert server.API_KEY is not None
    assert server.ATHLETE_ID is not None
    response = await server.get_power_curves(
        athlete_id=server.ATHLETE_ID, api_key=server.API_KEY
    )
    print(response)
    # Save the response to power_curves.json
    with open("power_curves.json", "w") as f:
        json.dump(response, f)


@pytest.mark.asyncio
async def test_server_get_pace_curves():
    env = load_dotenv()
    assert env is not None
    assert server.API_KEY is not None
    assert server.ATHLETE_ID is not None
    response = await server.get_pace_curves(
        athlete_id=server.ATHLETE_ID, api_key=server.API_KEY
    )
    print(response)
    # Save the response to pace_curves.json
    with open("pace_curves.json", "w") as f:
        json.dump(response, f)


@pytest.mark.asyncio
async def test_server_get_activity_power_curves():
    env = load_dotenv()
    assert env is not None
    assert server.API_KEY is not None
    assert server.ATHLETE_ID is not None
    response = await server.get_activity_power_curves(
        activity_id="i77881313", api_key=server.API_KEY
    )
    print(response)
    # Save the response to activity_power_curves.json
    with open("activity_power_curves.json", "w") as f:
        json.dump(response, f)


@pytest.mark.asyncio
async def test_server_get_athlete():
    env = load_dotenv()
    assert env is not None
    assert server.API_KEY is not None
    assert server.ATHLETE_ID is not None
    response = await server.get_athlete(
        athlete_id=server.ATHLETE_ID,
        api_key=server.API_KEY,
    )
    print(response)
    # Save the response to athlete.json
    with open("athlete.json", "w") as f:
        json.dump(response, f)


@pytest.mark.asyncio
async def test_server_get_activity_pace_curve():
    env = load_dotenv()
    assert env is not None
    assert server.API_KEY is not None
    assert server.ATHLETE_ID is not None
    response = await server.get_activity_pace_curve(
        activity_id="i78699351",
        api_key=server.API_KEY,
    )
    print(response)
    # Save the response to activity_pace_curve.json
    with open("activity_pace_curve.json", "w") as f:
        json.dump(response, f)
