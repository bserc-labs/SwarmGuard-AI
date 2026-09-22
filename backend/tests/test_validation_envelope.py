"""A 422 must not hand the rejected value back.

Found by the live exercise: FastAPI's default validation body repeats each
offending value under `input`, so a password that failed the length rule on
POST /users/ came straight back in the response. The body now carries only
where, what and why -- and the same `error` key every other error has.
"""

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_a_rejected_value_is_not_echoed():
    # No auth needed: the form is validated before the credentials are looked at.
    res = client.post("/auth/login", data={"username": "someone"})  # password missing
    assert res.status_code == 422
    body = res.json()
    assert body["error"] == "Validation Error"
    assert isinstance(body["detail"], list) and body["detail"]
    assert set(body["detail"][0]) <= {"type", "loc", "msg"}
    assert "input" not in res.text and "someone" not in res.text


def test_a_secret_in_the_body_stays_on_the_server():
    secret = "hunter2-is-too-short"
    res = client.post("/auth/login", data={"username": "x" * 300, "password": secret})
    if res.status_code != 422:
        # The username limit may not be enforced at validation; force one that is.
        res = client.post("/users/", json={"username": "u", "email": "not-an-email", "password": secret})
    assert res.status_code in (401, 422)
    assert secret not in res.text


def test_the_frontend_contract_is_kept():
    """frontend/src/services/api.ts joins detail[].msg into one message."""
    res = client.post("/auth/login", data={})
    assert res.status_code == 422
    assert all(isinstance(d.get("msg"), str) and d.get("loc") for d in res.json()["detail"])
