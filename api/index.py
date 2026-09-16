"""Vercel serverless entry point — exposes the MCP ASGI app.

Auth configuration happens at import time in server.py, driven by
MCP_ISSUER_URL (set in the Vercel project environment).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

if not os.getenv("MCP_ISSUER_URL"):
    raise RuntimeError("MCP_ISSUER_URL must be set in the Vercel environment")

from intervals_mcp_server.server import build_http_app

app = build_http_app()
