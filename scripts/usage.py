"""Show the usage log (see src/intervals_mcp_server/usage.py).

    uv run --env-file .env.local python scripts/usage.py              # calls per athlete, last 7 days
    uv run --env-file .env.local python scripts/usage.py --days 35    # whole retention window
    uv run --env-file .env.local python scripts/usage.py i12345       # one athlete, every call

Get .env.local with `npx vercel env pull`. Uses the read-only token when present.
"""

import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import httpx


def _redis():
    url = os.environ["KV_REST_API_URL"].rstrip("/")
    token = os.getenv("KV_REST_API_READ_ONLY_TOKEN") or os.environ["KV_REST_API_TOKEN"]
    client = httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=10)

    def call(*command):
        response = client.post(url, json=[str(c) for c in command])
        response.raise_for_status()
        return response.json()["result"]

    return call


def _keys(call, pattern):
    cursor, keys = "0", []
    while True:
        cursor, batch = call("SCAN", cursor, "MATCH", pattern, "COUNT", 1000)
        keys.extend(batch)
        if cursor == "0":
            return keys


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("athlete", nargs="?", help="show every call by this athlete")
    parser.add_argument("--days", type=int, default=7, help="how many days back (default 7)")
    args = parser.parse_args()

    call = _redis()
    today = datetime.now(timezone.utc).date()
    days = {(today - timedelta(days=n)).isoformat() for n in range(args.days)}
    keys = sorted(
        k for k in _keys(call, f"usage:{args.athlete or '*'}:*") if k.rsplit(":", 1)[1] in days
    )
    if not keys:
        print("No usage in that window.")
        return

    if args.athlete:
        for key in keys:
            day = key.rsplit(":", 1)[1]
            for entry in call("LRANGE", key, 0, -1):
                print(f"{day} {entry}")
        return

    totals, per_tool = Counter(), {}
    for key in keys:
        athlete = key.split(":")[1]
        entries = call("LRANGE", key, 0, -1)
        totals[athlete] += len(entries)
        per_tool.setdefault(athlete, Counter()).update(e.split(" ", 1)[1] for e in entries)

    print(f"Tool calls, last {args.days} days (UTC):\n")
    for athlete, total in totals.most_common():
        top = ", ".join(f"{tool} {n}" for tool, n in per_tool[athlete].most_common(3))
        print(f"{athlete:>12}  {total:>6}  {top}")


if __name__ == "__main__":
    sys.exit(main())
