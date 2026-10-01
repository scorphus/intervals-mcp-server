# Contributor Guide

MCP server for Intervals.icu. Python 3.12+, MCP SDK 2.x, httpx. Code in
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
```

`tests/real` hits the live Intervals.icu API and needs real credentials —
don't run it in CI.

## Deploying

Push to `main`. Vercel builds and deploys it; the landing page footer shows
the deployed commit. No manual deploys.
