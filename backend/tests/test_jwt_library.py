"""The JWT library is PyJWT, and nothing about the tokens changed with it.

python-jose was replaced because it pulled in `ecdsa`, whose advisory
PYSEC-2026-1325 has no fixed version. The risk in swapping an auth library is
silent behaviour change, so these pin what must not move: the token format,
exp enforcement, the refusal of `alg: none` and of algorithm confusion, and
that a token written the way python-jose wrote it still verifies.
"""

import base64
import hashlib
import hmac
import importlib.util
import json
import time
from datetime import timedelta

import jwt
import pytest

from services import auth_service


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def hand_signed(payload: dict, key: str, header: dict | None = None) -> str:
    """A JWT built from first principles: what python-jose produced for HS256."""
    head = _b64(json.dumps(header or {"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(key.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{_b64(sig)}"


def test_the_vulnerable_dependency_chain_is_gone():
    for module in ("jose", "ecdsa"):
        assert importlib.util.find_spec(module) is None, f"{module} is still installed"


def test_a_token_issued_before_the_switch_still_verifies():
    """Live sessions must survive the upgrade."""
    token = hand_signed({"sub": "alice", "role": "admin", "exp": int(time.time()) + 600}, auth_service.SECRET_KEY)
    assert auth_service.decode_access_token(token)["sub"] == "alice"


def test_new_tokens_are_plain_hs256():
    token = auth_service.create_access_token({"sub": "alice"})
    header = json.loads(base64.urlsafe_b64decode(token.split(".")[0] + "=="))
    assert header["alg"] == "HS256"


def test_an_expired_token_is_refused():
    token = auth_service.create_access_token({"sub": "alice"}, timedelta(seconds=-1))
    assert auth_service.decode_access_token(token) is None


def test_alg_none_is_refused():
    unsigned = hand_signed({"sub": "alice", "exp": int(time.time()) + 600}, "", {"alg": "none", "typ": "JWT"})
    unsigned = unsigned.rsplit(".", 1)[0] + "."
    assert auth_service.decode_access_token(unsigned) is None


def test_a_different_algorithm_is_refused_even_with_the_right_key():
    token = jwt.encode({"sub": "alice", "exp": int(time.time()) + 600}, auth_service.SECRET_KEY, algorithm="HS512")
    assert auth_service.decode_access_token(token) is None


@pytest.mark.parametrize("garbage", ["", "a.b", "a.b.c", "not-a-jwt-at-all"])
def test_garbage_is_refused_not_raised(garbage):
    assert auth_service.decode_access_token(garbage) is None
