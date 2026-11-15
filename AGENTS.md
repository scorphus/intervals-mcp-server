# Contributor Guide

MCP server for Intervals.icu. Python 3.12+ (runs on 3.14 in production and
CI, pinned by `.python-version`), MCP SDK 2.x, httpx. Code in
`src/intervals_mcp_server`, tests in `tests`.

## Setup

```
uv sync --all-extras
```

## Running

- stdio (Claude Desktop): `python -m intervals_mcp_server.server` with
  `API_KEY` and `ATHLETE_ID` set (see `.env.example`).
- HTTP with OAuth: `MCP_TRANSPORT=streamable-http python -m intervals_mcp_server.server`.

## Before committing

```
pytest tests --ignore=tests/real
ruff check src api
pylint --disable=C,R src api scripts
```

CI runs the same pytest and pylint commands. `tests/real` hits the live
Intervals.icu API and needs real credentials — don't run it in CI.

## Deploying

Push to `main`. Vercel builds and deploys it; the landing page footer shows
the deployed commit. No manual deploys.
