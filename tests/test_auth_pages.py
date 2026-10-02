import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from starlette.requests import Request  # noqa: E402

from intervals_mcp_server import auth  # noqa: E402


def _request(path, query=b""):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": query,
            "headers": [(b"host", b"example.com")],
            "scheme": "https",
            "server": ("example.com", 443),
        }
    )


def _sign_in_page(error):
    pending = auth._mint_jwt({"type": "pending"}, ttl=60)
    query = f"request_id={pending}&error={error}".encode()
    page = auth.IntervalsOAuthProvider().handle_auth_page(_request("/intervals-auth", query))
    return asyncio.run(page).body.decode()


def test_sign_in_page_shows_known_error():
    assert "Both fields are required" in _sign_in_page("missing_fields")


def test_sign_in_page_ignores_text_from_url():
    page = _sign_in_page("%3Ca%20href%3D%22https%3A%2F%2Fevil%22%3Eevil%3C%2Fa%3E")
    assert "evil" not in page


def test_sign_in_page_explains_how_to_request_access():
    page = _sign_in_page("access_closed")
    assert "Access is currently closed." in page
    assert auth.ACCESS_REQUEST_HTML in page
