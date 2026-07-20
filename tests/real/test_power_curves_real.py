"""
Manual test script for get_activity_power_curves using real API credentials.
"""

import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

import sys

sys.path.insert(0, "src")

from intervals_mcp_server.server import get_activity_power_curves, get_activities


async def test():
    # First get recent activities to find an activity ID
    activities_result = await get_activities(athlete_id=os.getenv("ATHLETE_ID"), limit=5)
    print("Recent activities:")
    print(activities_result)
    print("\n" + "=" * 80 + "\n")

    # You'll need to provide ACTIVITY_ID in .env
    activity_id = os.getenv("ACTIVITY_ID")

    if activity_id:
        result = await get_activity_power_curves(activity_id)
        print(f"\nPower curves for activity {activity_id}:")
        print(result)
    else:
        print("No activity ID provided")


if __name__ == "__main__":
    asyncio.run(test())
