"""Fully stateless OAuth provider for Intervals.icu MCP server.

Every piece of state — client registrations, auth codes, pending requests,
access tokens, refresh tokens — is encoded as a signed JWT. The server
stores nothing; it only needs JWT_SECRET to verify signatures.

Sensitive fields (api_key) are encrypted with Fernet before being placed
in the JWT payload, so intercepted tokens cannot leak credentials.
"""

import base64
import hashlib
import hmac
import os
import secrets
import time

import jwt
from cryptography.fernet import Fernet
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_urlsafe(32))
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = 86400 * 30
REFRESH_TOKEN_TTL = 86400 * 90

_fernet_key = base64.urlsafe_b64encode(
    hashlib.sha256(JWT_SECRET.encode()).digest()
)
_fernet = Fernet(_fernet_key)


def _encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    return _fernet.decrypt(ciphertext.encode()).decode()


class IntervalsAccessToken(AccessToken):
    intervals_api_key: str
    intervals_athlete_id: str


class IntervalsRefreshToken(RefreshToken):
    intervals_api_key: str
    intervals_athlete_id: str


class IntervalsAuthCode(AuthorizationCode):
    intervals_api_key: str
    intervals_athlete_id: str


def _mint_jwt(payload: dict, ttl: int) -> str:
    now = int(time.time())
    payload = {**payload, "iat": now, "exp": now + ttl}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_jwt(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def _derive_client_secret(client_id: str) -> str:
    return hmac.new(
        JWT_SECRET.encode(), client_id.encode(), hashlib.sha256
    ).hexdigest()


class IntervalsOAuthProvider:

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        claims = _decode_jwt(client_id)
        if not claims or claims.get("type") != "client":
            return None
        return OAuthClientInformationFull(
            client_id=client_id,
            client_secret=_derive_client_secret(client_id),
            redirect_uris=claims["redirect_uris"],
            token_endpoint_auth_method=claims.get("auth_method", "client_secret_post"),
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        )

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        client_info.client_id = _mint_jwt(
            {
                "type": "client",
                "redirect_uris": [str(u) for u in client_info.redirect_uris],
                "auth_method": client_info.token_endpoint_auth_method,
            },
            ttl=86400 * 365 * 10,
        )
        client_info.client_secret = _derive_client_secret(client_info.client_id)

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        request_id = _mint_jwt(
            {
                "type": "pending",
                "client_id": client.client_id,
                "state": params.state,
                "scopes": params.scopes,
                "code_challenge": params.code_challenge,
                "redirect_uri": str(params.redirect_uri),
                "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            },
            ttl=600,
        )
        return f"/intervals-auth?request_id={request_id}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> IntervalsAuthCode | None:
        claims = _decode_jwt(authorization_code)
        if not claims or claims.get("type") != "auth_code":
            return None
        if claims["client_id"] != client.client_id:
            return None
        return IntervalsAuthCode(
            code=authorization_code,
            scopes=claims.get("scopes", []),
            expires_at=claims["exp"],
            client_id=claims["client_id"],
            code_challenge=claims["code_challenge"],
            redirect_uri=claims["redirect_uri"],
            redirect_uri_provided_explicitly=claims["redirect_uri_provided_explicitly"],
            intervals_api_key=_decrypt(claims["api_key"]),
            intervals_athlete_id=claims["athlete_id"],
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: IntervalsAuthCode
    ) -> OAuthToken:
        jwt_payload = {
            "client_id": client.client_id,
            "scopes": authorization_code.scopes,
            "api_key": _encrypt(authorization_code.intervals_api_key),
            "athlete_id": authorization_code.intervals_athlete_id,
            "type": "access",
        }
        access_token = _mint_jwt(jwt_payload, ACCESS_TOKEN_TTL)

        jwt_payload["type"] = "refresh"
        refresh_token = _mint_jwt(jwt_payload, REFRESH_TOKEN_TTL)

        return OAuthToken(
            access_token=access_token,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_TTL,
            refresh_token=refresh_token,
            scope=" ".join(authorization_code.scopes),
        )

    async def load_access_token(self, token: str) -> IntervalsAccessToken | None:
        claims = _decode_jwt(token)
        if not claims or claims.get("type") != "access":
            return None
        return IntervalsAccessToken(
            token=token,
            client_id=claims["client_id"],
            scopes=claims.get("scopes", []),
            expires_at=claims.get("exp"),
            intervals_api_key=_decrypt(claims["api_key"]),
            intervals_athlete_id=claims["athlete_id"],
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> IntervalsRefreshToken | None:
        claims = _decode_jwt(refresh_token)
        if not claims or claims.get("type") != "refresh":
            return None
        if claims["client_id"] != client.client_id:
            return None
        return IntervalsRefreshToken(
            token=refresh_token,
            client_id=claims["client_id"],
            scopes=claims.get("scopes", []),
            intervals_api_key=_decrypt(claims["api_key"]),
            intervals_athlete_id=claims["athlete_id"],
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: IntervalsRefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        jwt_payload = {
            "client_id": client.client_id,
            "scopes": scopes,
            "api_key": _encrypt(refresh_token.intervals_api_key),
            "athlete_id": refresh_token.intervals_athlete_id,
            "type": "access",
        }
        access_token = _mint_jwt(jwt_payload, ACCESS_TOKEN_TTL)

        jwt_payload["type"] = "refresh"
        new_refresh_token = _mint_jwt(jwt_payload, REFRESH_TOKEN_TTL)

        return OAuthToken(
            access_token=access_token,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_TTL,
            refresh_token=new_refresh_token,
            scope=" ".join(scopes),
        )

    async def revoke_token(
        self,
        token: IntervalsAccessToken | IntervalsRefreshToken,
    ) -> None:
        pass

    # --- Custom auth page ---

    async def handle_auth_page(self, request: Request):
        request_id = request.query_params.get("request_id", "")
        claims = _decode_jwt(request_id)
        if not claims or claims.get("type") != "pending":
            return HTMLResponse("Invalid or expired auth request.", status_code=400)

        error = request.query_params.get("error", "")
        error_html = (
            f'<p style="color:#e74c3c;margin-bottom:1rem">{error}</p>' if error else ""
        )

        return HTMLResponse(
            AUTH_PAGE_HTML.replace("{{request_id}}", request_id).replace(
                "{{error}}", error_html
            )
        )

    async def handle_auth_submit(self, request: Request):
        form = await request.form()
        request_id = str(form.get("request_id", ""))
        api_key = str(form.get("api_key", "")).strip()
        athlete_id = str(form.get("athlete_id", "")).strip()

        claims = _decode_jwt(request_id)
        if not claims or claims.get("type") != "pending":
            return HTMLResponse("Invalid or expired auth request.", status_code=400)

        if not api_key or not athlete_id:
            return RedirectResponse(
                f"/intervals-auth?request_id={request_id}&error=Both+fields+are+required",
                status_code=302,
            )

        code = _mint_jwt(
            {
                "type": "auth_code",
                "client_id": claims["client_id"],
                "scopes": claims.get("scopes") or [],
                "code_challenge": claims["code_challenge"],
                "redirect_uri": claims["redirect_uri"],
                "redirect_uri_provided_explicitly": claims["redirect_uri_provided_explicitly"],
                "api_key": _encrypt(api_key),
                "athlete_id": athlete_id,
            },
            ttl=300,
        )

        return RedirectResponse(
            construct_redirect_uri(
                claims["redirect_uri"], code=code, state=claims.get("state")
            ),
            status_code=302,
        )


AUTH_PAGE_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connect to Intervals.icu</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f5f5f5; display: flex; justify-content: center; align-items: center;
    min-height: 100vh; padding: 1rem;
  }
  .card {
    background: #fff; border-radius: 12px; padding: 2rem; max-width: 420px;
    width: 100%; box-shadow: 0 2px 12px rgba(0,0,0,0.1);
  }
  h1 { font-size: 1.4rem; margin-bottom: 0.5rem; }
  p { color: #666; font-size: 0.9rem; margin-bottom: 1.2rem; line-height: 1.4; }
  label { display: block; font-weight: 600; margin-bottom: 0.4rem; font-size: 0.9rem; }
  input[type="password"], input[type="text"] {
    width: 100%; padding: 0.7rem; border: 1px solid #ddd; border-radius: 8px;
    font-size: 1rem; margin-bottom: 1.2rem;
  }
  input[type="password"]:focus, input[type="text"]:focus { outline: none; border-color: #4a90d9; }
  button {
    width: 100%; padding: 0.75rem; background: #4a90d9; color: #fff; border: none;
    border-radius: 8px; font-size: 1rem; font-weight: 600; cursor: pointer;
  }
  button:hover { background: #3a7bc8; }
  .help { font-size: 0.8rem; color: #999; margin-top: 1rem; }
  .help a { color: #4a90d9; }
</style>
</head>
<body>
<div class="card">
  <h1>Connect to Intervals.icu</h1>
  <p>Enter your Intervals.icu credentials to allow Claude to access your training data.</p>
  {{error}}
  <form method="POST" action="/intervals-auth">
    <input type="hidden" name="request_id" value="{{request_id}}">
    <label for="athlete_id">Athlete ID</label>
    <input type="text" id="athlete_id" name="athlete_id" placeholder="e.g. i12345" required>
    <label for="api_key">API Key</label>
    <input type="password" id="api_key" name="api_key" placeholder="Paste your API key" required>
    <button type="submit">Connect</button>
  </form>
  <p class="help">
    Find both at
    <a href="https://intervals.icu/settings" target="_blank">intervals.icu/settings</a>
    &mdash; Athlete ID is at the top, API key under "Developer Settings".
  </p>
</div>
</body>
</html>
"""
