# Intervals.icu MCP Server

[Model Context Protocol](https://modelcontextprotocol.io/) server for connecting Claude with the [Intervals.icu](https://intervals.icu) API. Analyze your training data, manage events and workouts, and track wellness — all through natural conversation.

## Quick Start (Hosted)

The easiest way to use this server is via the hosted instance — no installation required.

1. Open the Claude app (mobile or desktop)
2. Go to **Settings > Connectors > Add Connector**
3. Enter the URL: `https://intervals-better-mcp.vercel.app/mcp`
4. Follow the OAuth flow to enter your Intervals.icu **Athlete ID** and **API Key**

That's it. Ask Claude about your training data.

### Finding your credentials

- **Athlete ID**: visible in the URL when logged into Intervals.icu — `https://intervals.icu/athlete/i12345/...` where `i12345` is your ID
- **API Key**: go to [intervals.icu/settings](https://intervals.icu/settings), scroll to **Developer Settings**

## Local Setup

If you prefer to run the server locally (e.g., for development or privacy):

### 1. Clone and install

```bash
git clone https://github.com/scorphus/intervals-mcp-server.git
cd intervals-mcp-server
uv sync
```

### 2. Configure credentials

```bash
cp .env.example .env
```

Edit `.env` with your Intervals.icu credentials:

```
API_KEY=your_api_key_here
ATHLETE_ID=i12345
```

### 3. Add to Claude Desktop

Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "Intervals.icu": {
      "command": "uv",
      "args": [
        "run",
        "--with", "mcp[cli]",
        "--with-editable", "/path/to/intervals-mcp-server",
        "mcp", "run",
        "/path/to/intervals-mcp-server/src/intervals_mcp_server/server.py"
      ],
      "env": {
        "ATHLETE_ID": "i12345",
        "API_KEY": "your_api_key_here"
      }
    }
  }
}
```

Replace `/path/to/intervals-mcp-server` with the actual path on your system.

## Available Tools

### Activities
- `get_activities` — list activities in a date range
- `get_activity_details` — detailed info for a specific activity
- `get_activity_intervals` — interval/lap data with formatted paces and power
- `get_activity_messages` — comments and notes on an activity
- `add_activity_message` — add a comment to an activity

### Events & Workouts
- `list_events` — list calendar events in a date range
- `get_event_by_id` — detailed event info
- `add_or_update_event` — create or update events and workouts
- `delete_event` — delete a single event
- `delete_events_by_date_range` — bulk delete events
- `download_workout_zwo` — export a workout as a ZWO file

### Performance Analysis
- `get_power_curves` — athlete power curve over a date range
- `get_activity_power_curves` — power curve for a single activity
- `get_pace_curves` — athlete pace curve over a date range
- `get_activity_pace_curve` — pace curve for a single activity
- `get_power_hr_curve` — power vs heart rate relationship
- `get_activity_power_vs_hr` — power vs HR for a single activity
- `get_activity_hr_curve` — heart rate curve for a single activity

### Athlete & Wellness
- `get_athlete` — athlete profile and settings
- `get_wellness_data` — daily wellness metrics (weight, HRV, sleep, mood, etc.)
- `get_gear_list` — bikes, shoes, and other equipment

### Notes & Utilities
- `add_or_update_note` — create or update a note
- `get_current_date_and_time_info` — current date/time with training context
- `calculate_date_info` — date arithmetic and week boundaries

## Development

```bash
uv sync --all-extras
pytest -v tests
```

To run the server locally in HTTP mode (for testing OAuth and multi-user):

```bash
MCP_TRANSPORT=streamable-http MCP_ISSUER_URL=http://localhost:8000 python -m intervals_mcp_server.server
```

## License

[GNU General Public License v3.0](LICENSE)
