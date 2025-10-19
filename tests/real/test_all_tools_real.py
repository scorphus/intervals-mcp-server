"""
Manual test script for all new MCP tools using real API credentials.

New tools being tested:
- list_events
- get_power_curves
- get_activity_power_curves
- get_pace_curves
- get_activity_pace_curve
- get_power_hr_curve
- get_activity_power_vs_hr
- get_activity_hr_curve
"""
import asyncio
import os
from dotenv import load_dotenv
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
    get_activities,
)


async def test_list_events():
    """Test list_events"""
    print("\n" + "="*80)
    print("Testing list_events")
    print("="*80)

    result = await list_events(
        athlete_id=os.getenv('ATHLETE_ID'),
        limit=5,
    )
    print(f"\nResult type: {type(result)}")
    if isinstance(result, list):
        print(f"Number of events: {len(result)}")
        if result:
            print(f"\nFirst event:")
            print(result[0])
    else:
        print(result)


async def test_get_power_curves():
    """Test get_power_curves"""
    print("\n" + "="*80)
    print("Testing get_power_curves")
    print("="*80)

    result = await get_power_curves(
        athlete_id=os.getenv('ATHLETE_ID'),
        curves="42d",
        type_="Ride",
    )
    print(f"\nResult type: {type(result)}")
    if isinstance(result, list):
        print(f"Number of curve points: {len(result)}")
        if result:
            print(f"\nFirst few entries:")
            for entry in result[:3]:
                print(entry)
    else:
        print(result)


async def test_get_activity_power_curves():
    """Test get_activity_power_curves"""
    print("\n" + "="*80)
    print("Testing get_activity_power_curves")
    print("="*80)

    # Get a recent activity with power data
    activity_id = input("Enter a cycling activity ID (or press Enter to skip): ").strip()
    if not activity_id:
        print("Skipped")
        return

    result = await get_activity_power_curves(activity_id)
    print(f"\nResult type: {type(result)}")
    if isinstance(result, list) and result:
        print(f"Number of entries: {len(result)}")
        print(f"\nFirst entry keys: {result[0].keys() if isinstance(result[0], dict) else 'N/A'}")
        if isinstance(result[0], dict) and 'secs' in result[0]:
            print(f"Number of time points: {len(result[0]['secs'])}")
    else:
        print(result)


async def test_get_pace_curves():
    """Test get_pace_curves"""
    print("\n" + "="*80)
    print("Testing get_pace_curves")
    print("="*80)

    result = await get_pace_curves(
        athlete_id=os.getenv('ATHLETE_ID'),
        curves="42d",
        type_="Run",
    )
    print(f"\nResult type: {type(result)}")
    if isinstance(result, list):
        print(f"Number of curve points: {len(result)}")
        if result:
            print(f"\nFirst few entries:")
            for entry in result[:3]:
                print(entry)
    else:
        print(result)


async def test_get_activity_pace_curve():
    """Test get_activity_pace_curve"""
    print("\n" + "="*80)
    print("Testing get_activity_pace_curve")
    print("="*80)

    # Get a recent running activity
    activity_id = input("Enter a running activity ID (or press Enter to skip): ").strip()
    if not activity_id:
        print("Skipped")
        return

    result = await get_activity_pace_curve(activity_id)
    print(f"\nResult type: {type(result)}")
    if isinstance(result, dict):
        print(f"Keys: {result.keys()}")
        if 'secs' in result:
            print(f"Number of time points: {len(result['secs'])}")
    else:
        print(result)


async def test_get_power_hr_curve():
    """Test get_power_hr_curve"""
    print("\n" + "="*80)
    print("Testing get_power_hr_curve")
    print("="*80)

    result = await get_power_hr_curve(
        athlete_id=os.getenv('ATHLETE_ID'),
        start_date="2025-09-01",
        end_date="2025-10-03",
    )
    print(f"\nResult type: {type(result)}")
    if isinstance(result, dict):
        print(f"Keys: {result.keys()}")
        if 'buckets' in result:
            print(f"Number of buckets: {len(result['buckets'])}")
            print(f"\nFirst bucket: {result['buckets'][0] if result['buckets'] else 'None'}")
    else:
        print(result)


async def test_get_activity_power_vs_hr():
    """Test get_activity_power_vs_hr"""
    print("\n" + "="*80)
    print("Testing get_activity_power_vs_hr")
    print("="*80)

    # Get a recent activity with power and HR data
    activity_id = input("Enter a cycling activity ID with HR (or press Enter to skip): ").strip()
    if not activity_id:
        print("Skipped")
        return

    result = await get_activity_power_vs_hr(activity_id)
    print(f"\nResult type: {type(result)}")
    if isinstance(result, dict):
        print(f"Keys: {result.keys()}")
        if 'buckets' in result:
            print(f"Number of buckets: {len(result['buckets'])}")
    else:
        print(result)


async def test_get_activity_hr_curve():
    """Test get_activity_hr_curve"""
    print("\n" + "="*80)
    print("Testing get_activity_hr_curve")
    print("="*80)

    # Get a recent activity with HR data
    activity_id = input("Enter an activity ID with HR (or press Enter to skip): ").strip()
    if not activity_id:
        print("Skipped")
        return

    result = await get_activity_hr_curve(activity_id)
    print(f"\nResult type: {type(result)}")
    if isinstance(result, dict):
        print(f"Keys: {result.keys()}")
        if 'secs' in result:
            print(f"Number of time points: {len(result['secs'])}")
    else:
        print(result)


async def main():
    """Run all tests"""
    print("\nTesting all new MCP tools with real API")
    print("="*80)

    # Tests that don't need activity IDs
    await test_list_events()
    await test_get_power_curves()
    await test_get_pace_curves()
    await test_get_power_hr_curve()

    # Tests that need activity IDs (interactive)
    print("\n\nThe following tests require activity IDs.")
    print("You can find activity IDs from recent activities.")

    # Show recent activities
    print("\n" + "="*80)
    print("Recent Activities")
    print("="*80)
    activities = await get_activities(athlete_id=os.getenv('ATHLETE_ID'), limit=5)
    print(activities)

    await test_get_activity_power_curves()
    await test_get_activity_pace_curve()
    await test_get_activity_power_vs_hr()
    await test_get_activity_hr_curve()

    print("\n" + "="*80)
    print("All tests completed!")
    print("="*80)


if __name__ == '__main__':
    asyncio.run(main())
