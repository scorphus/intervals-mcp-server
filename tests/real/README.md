# Real API Tests

This directory contains manual test scripts that interact with the real Intervals.icu API.

## Prerequisites

- Valid `.env` file with `API_KEY` and `ATHLETE_ID` in the project root
- Active internet connection
- Valid Intervals.icu account with data

## Running Tests

### Test All New Tools

Run the comprehensive test for all newly implemented tools:

```bash
python tests/real/test_all_tools_real.py
```

This will test:
- `list_events` - List athlete events
- `get_races` - Get race events
- `get_power_curves` - Get athlete power curves
- `get_activity_power_curves` - Get power curves for a specific activity
- `get_pace_curves` - Get athlete pace curves
- `get_activity_pace_curve` - Get pace curve for a specific activity
- `get_power_hr_curve` - Get power vs HR curve
- `get_activity_power_vs_hr` - Get power vs HR for a specific activity
- `get_activity_hr_curve` - Get HR curve for a specific activity

### Test Specific Tool

For testing a specific activity's power curves:

```bash
python tests/real/test_power_curves_real.py
```

## Notes

- Some tests require activity IDs as input
- The comprehensive test script will show recent activities to help you select IDs
- Tests may take a few seconds to complete due to API calls
- Errors may occur if you don't have the required data types (e.g., power meter data, HR data)
