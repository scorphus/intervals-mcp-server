"""Vercel serverless entry point — exposes the MCP ASGI app."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from intervals_mcp_server.auth import IntervalsOAuthProvider
from intervals_mcp_server.server import mcp
from mcp.server.auth.provider import ProviderTokenVerifier
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.transport_security import TransportSecuritySettings

issuer_url = os.environ["MCP_ISSUER_URL"]
resource_url = os.getenv("MCP_RESOURCE_URL", issuer_url)

auth_provider = IntervalsOAuthProvider()
mcp.settings.stateless_http = True
mcp.settings.transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=False,
)
mcp.settings.auth = AuthSettings(
    issuer_url=issuer_url,
    resource_server_url=resource_url,
    client_registration_options=ClientRegistrationOptions(enabled=True),
)
mcp._auth_server_provider = auth_provider
mcp._token_verifier = ProviderTokenVerifier(auth_provider)


@mcp.custom_route("/", methods=["GET"])
async def landing(request):
    return await auth_provider.handle_landing_page(request)


@mcp.custom_route("/intervals-auth", methods=["GET"])
async def auth_page(request):
    return await auth_provider.handle_auth_page(request)


@mcp.custom_route("/intervals-auth", methods=["POST"])
async def auth_submit(request):
    return await auth_provider.handle_auth_submit(request)


app = mcp.streamable_http_app()
