import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from intervals_mcp_server import auth  # noqa: E402


def _access_token(athlete_id):
    return auth._mint_jwt(
        {
            "type": "access",
            "client_id": "c",
            "scopes": [],
            "api_key": auth._encrypt("key"),
            "athlete_id": athlete_id,
        },
        ttl=60,
    )


def _load(token):
    return asyncio.run(auth.IntervalsOAuthProvider().load_access_token(token))


def test_no_allowlist_lets_everyone_in(monkeypatch):
    monkeypatch.setattr(auth, "ALLOWED_ATHLETE_IDS", set())
    assert _load(_access_token("i1")) is not None


def test_allowlist_accepts_listed_athlete(monkeypatch):
    monkeypatch.setattr(auth, "ALLOWED_ATHLETE_IDS", {"i12345"})
    assert _load(_access_token("i12345")) is not None


def test_allowlist_rejects_existing_token_of_unlisted_athlete(monkeypatch):
    monkeypatch.setattr(auth, "ALLOWED_ATHLETE_IDS", {"i12345"})
    assert _load(_access_token("i99999")) is None
