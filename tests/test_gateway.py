import os
import time

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret")

from app import main  # noqa: E402
from app.config import settings  # noqa: E402
from app.ratelimit import limiter  # noqa: E402

SECRET = settings.jwt_secret
llamadas = []


def upstream(request: httpx.Request) -> httpx.Response:
    llamadas.append(request)
    if request.url.path == "/health":
        return httpx.Response(200, json={"status": "ok"})
    return httpx.Response(200, json={"eco": request.url.path, "uid": request.headers.get("x-user-id")})


@pytest.fixture(autouse=True)
def entorno():
    llamadas.clear()
    limiter.reset()
    main._client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    settings.auth_enforce = True
    yield


def token(role="cliente", exp=3600):
    return jwt.encode({"sub": "u-1", "role": role, "exp": time.time() + exp}, SECRET, algorithm="HS256")


c = TestClient(main.app)


def test_ruta_publica_sin_token():
    r = c.get("/transfer/transfers/trm")
    assert r.status_code == 200 and r.json()["eco"] == "/transfers/trm"


def test_sin_token_rechaza():
    assert c.get("/account/accounts").status_code == 401
    assert not llamadas


def test_token_invalido_y_vencido():
    assert c.get("/account/accounts", headers={"Authorization": "Bearer xxx"}).status_code == 401
    assert c.get("/account/accounts", headers={"Authorization": f"Bearer {token(exp=-10)}"}).status_code == 401


def test_token_valido_enruta_y_propaga_usuario():
    r = c.get("/account/accounts", headers={"Authorization": f"Bearer {token()}"})
    assert r.status_code == 200 and r.json() == {"eco": "/accounts", "uid": "u-1"}
    assert "x-request-id" in r.headers


def test_admin_requerido_en_compliance():
    assert c.get("/compliance/compliance/reportes", headers={"Authorization": f"Bearer {token()}"}).status_code == 403
    assert c.get("/compliance/compliance/reportes", headers={"Authorization": f"Bearer {token('admin')}"}).status_code == 200


def test_servicio_desconocido():
    assert c.get("/nada/x", headers={"Authorization": f"Bearer {token()}"}).status_code == 404


def test_rate_limit_sensible():
    codigos = [c.post("/identity/auth/login", json={}).status_code for _ in range(settings.rate_limit_sensitive_per_minute + 2)]
    assert codigos[: settings.rate_limit_sensitive_per_minute] == [200] * settings.rate_limit_sensitive_per_minute
    assert codigos[-1] == 429
    assert c.post("/identity/auth/login", json={}).headers["retry-after"]


def test_login_publico_no_exige_token():
    assert c.post("/identity/auth/login", json={}).status_code == 200


def test_health_all():
    r = c.get("/health/all")
    assert r.status_code == 200 and r.json()["todos_ok"] is True and len(r.json()["servicios"]) == 8


def test_auth_desactivable_para_depurar():
    settings.auth_enforce = False
    assert c.get("/account/accounts").status_code == 200


def test_health_all_espera_a_que_despierte_un_servicio(monkeypatch):
    settings.health_retry_delay_seconds = 0
    estados = {"n": 0}

    def despertando(request: httpx.Request) -> httpx.Response:
        if "9002" in str(request.url):
            estados["n"] += 1
            return httpx.Response(429 if estados["n"] < 3 else 200, json={"status": "ok"})
        return httpx.Response(200, json={"status": "ok"})

    monkeypatch.setattr(settings, "account_service_url", "http://x:9002")
    main._client = httpx.AsyncClient(transport=httpx.MockTransport(despertando))
    r = c.get("/health/all")
    assert r.status_code == 200 and r.json()["servicios"]["account"]["intentos"] == 3


def test_health_all_reporta_el_que_no_despierta(monkeypatch):
    settings.health_retry_delay_seconds = 0
    monkeypatch.setattr(settings, "health_retries", 3)
    monkeypatch.setattr(settings, "ledger_service_url", "http://x:9003")
    main._client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda rq: httpx.Response(502) if "9003" in str(rq.url) else httpx.Response(200, json={})))
    r = c.get("/health/all")
    assert r.status_code == 503 and r.json()["servicios"]["ledger"] == {"status": "http 502", "intentos": 3, "ms": r.json()["servicios"]["ledger"]["ms"]}
