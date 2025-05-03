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
    """
    async def get_activities(
        athlete_id: str | None = None,
        api_key: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 10,
        include_unnamed: bool = False,
    ) -> str:
        ...
    """
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
async def test_server_get_events():
    """
    async def get_events(
        athlete_id: str | None = None,
        api_key: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> str:
        \"""Get events for an athlete from Intervals.icu

        Args:
            athlete_id: The Intervals.icu athlete ID (optional, will use ATHLETE_ID from .env if not provided)
            api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
            start_date: Start date in YYYY-MM-DD format (optional, defaults to today)
            end_date: End date in YYYY-MM-DD format (optional, defaults to 30 days from today)
        \"""
        ...
    """
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
