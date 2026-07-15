# Real API Tests

Tests that hit the real Intervals.icu API and save JSON responses to `output/`.

## Prerequisites

- `.env` with `API_KEY` and `ATHLETE_ID`
- Optional: `ACTIVITY_ID` env var for activity-specific tests

## Usage

```bash
# Run all tests
ACTIVITY_ID=i12345 uv run pytest tests/real/ -v

# Run a single tool
ACTIVITY_ID=i12345 uv run pytest tests/real/test_all_tools_real.py -k test_get_power_curves

# Without ACTIVITY_ID, activity-specific tests are skipped
uv run pytest tests/real/ -v
```

Output is saved to `tests/real/output/<tool_name>.json`.
