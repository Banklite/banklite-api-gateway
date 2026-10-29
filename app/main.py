"""API Gateway de BankLite: punto unico de entrada al backend.

Funciones: autenticacion JWT (valida el token que emite identity-service tras el MFA),
control de rol, rate limiting, enrutamiento hacia los 8 microservicios y logging.

Ruteo: /<servicio>/<ruta>  ->  <URL del servicio>/<ruta>
  ej.  GET /transfer/transfers/trm  ->  transfer-service  GET /transfers/trm
"""

import asyncio
import logging
import re
import time
import uuid

import httpx
import jwt
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .config import settings
from .ratelimit import limiter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(settings.service_name)

app = FastAPI(
    title="BankLite - API Gateway",
    description=(
        "Punto unico de entrada: JWT, rol admin, rate limiting y enrutamiento a los microservicios. "
        "Uso: /<servicio>/<ruta>, con servicio en identity, account, ledger, transfer, card, fraud, "
        "notification, compliance."
    ),
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    expose_headers=["X-Request-ID", "Retry-After"],
)

# (metodo, regex sobre "<servicio>/<ruta>"): no exigen token (registro, login, datos publicos).
_PUBLIC = [(m, re.compile(p)) for m, p in [
    ("POST", r"^identity/users$"),
    ("POST", r"^identity/kyc/verify$"),
    ("GET", r"^identity/users/validar-identidad/[^/]+$"),
    ("GET", r"^identity/users/ciudades-colombia$"),
    ("POST", r"^identity/auth/login$"),
    ("POST", r"^identity/auth/login/(solicitar|confirmar)-codigo$"),
    ("POST", r"^identity/auth/(solicitar-reset|reset-clave)$"),
    ("POST", r"^identity/auth/pin/(login|solicitar-codigo)$"),
    ("GET", r"^transfer/transfers/(trm|divisas)$"),
    ("GET", r"^account/accounts/puntos-cajero$"),
    ("GET", r"^[a-z]+/(health)$"),
]]
# Rutas sensibles: limite de peticiones mas estricto (fuerza bruta de claves / codigos).
_SENSITIVE = re.compile(r"^identity/(auth/(login|otp|pin|solicitar-reset|reset-clave)|users/[^/]+/cambiar-clave)")
_HOP = {"host", "content-length", "connection", "keep-alive", "transfer-encoding", "te", "upgrade",
        "proxy-authorization", "proxy-authenticate", "trailer", "content-encoding"}

_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=settings.upstream_timeout_seconds, follow_redirects=True)
    return _client


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


def _is_public(method: str, path: str) -> bool:
    return any(m == method and rx.match(path) for m, rx in _PUBLIC)


def _error(status: int, detail: str, rid: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status, headers={"X-Request-ID": rid, **(headers or {})})


@app.get("/health", tags=["infra"])
def health():
    return {"status": "ok", "service": settings.service_name}


@app.get("/health/all", tags=["infra"])
async def health_all():
    """Consulta /health de los 8 servicios en paralelo. Sirve para despertarlos (Render gratis)
    y como monitor: apuntar aqui un ping externo cada 5 min los mantiene activos."""

    async def one(name: str, url: str):
        t0 = time.monotonic()
        try:
            r = await _http().get(f"{url}/health")
            return name, {"status": "ok" if r.status_code == 200 else f"http {r.status_code}",
                          "ms": int((time.monotonic() - t0) * 1000)}
        except Exception as exc:  # noqa: BLE001
            return name, {"status": "caido", "error": type(exc).__name__, "ms": int((time.monotonic() - t0) * 1000)}

    resultados = dict(await asyncio.gather(*(one(n, u) for n, u in settings.upstreams.items())))
    todos = all(v["status"] == "ok" for v in resultados.values())
    return JSONResponse({"gateway": "ok", "todos_ok": todos, "servicios": resultados},
                        status_code=200 if todos else 503)


@app.api_route("/{service}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
               include_in_schema=False)
async def proxy(service: str, path: str, request: Request):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    t0 = time.monotonic()
    user = "-"
    status = 500
    try:
        base = settings.upstreams.get(service)
        if base is None:
            status = 404
            return _error(404, f"Servicio desconocido: {service}", rid)

        ruta = f"{service}/{path}"
        method = request.method
        ip = _client_ip(request)

        # --- rate limiting ---
        limite = settings.rate_limit_sensitive_per_minute if _SENSITIVE.match(ruta) else settings.rate_limit_per_minute
        clave = f"{ip}|{'sens' if limite == settings.rate_limit_sensitive_per_minute else 'gen'}"
        ok, retry = limiter.check(clave, limite)
        if not ok:
            status = 429
            return _error(429, "Demasiadas peticiones. Intenta de nuevo en unos segundos.", rid,
                          {"Retry-After": str(retry)})

        # --- autenticacion y autorizacion ---
        claims = None
        if method != "OPTIONS" and settings.auth_enforce and not _is_public(method, ruta):
            auth = request.headers.get("authorization", "")
            if not auth.lower().startswith("bearer "):
                status = 401
                return _error(401, "Falta el token de autenticacion", rid, {"WWW-Authenticate": "Bearer"})
            try:
                claims = jwt.decode(auth[7:].strip(), settings.jwt_secret, algorithms=[settings.jwt_algorithm])
            except jwt.PyJWTError:
                status = 401
                return _error(401, "Token invalido o expirado", rid, {"WWW-Authenticate": "Bearer"})
            user = claims.get("sub", "-")
            admin_pref = [p.strip() for p in settings.admin_prefixes.split(",") if p.strip()]
            if any(path.startswith(p) for p in admin_pref) and claims.get("role") != "admin":
                status = 403
                return _error(403, "Requiere rol administrador", rid)

        # --- enrutamiento ---
        headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP}
        headers["X-Request-ID"] = rid
        headers["X-Forwarded-For"] = ip
        if claims:
            headers["X-User-Id"] = str(claims.get("sub", ""))
            headers["X-User-Role"] = str(claims.get("role", ""))
        try:
            r = await _http().request(
                method, f"{base}/{path}", params=request.query_params, content=await request.body(), headers=headers
            )
        except httpx.TimeoutException:
            status = 504
            return _error(504, f"{service}-service no respondio a tiempo (puede estar despertando; reintenta)", rid)
        except httpx.HTTPError:
            status = 502
            return _error(502, f"No se pudo contactar a {service}-service", rid)

        status = r.status_code
        out = {k: v for k, v in r.headers.items() if k.lower() not in _HOP}
        out["X-Request-ID"] = rid
        return Response(content=r.content, status_code=r.status_code, headers=out)
    finally:
        logger.info("%s /%s/%s -> %s %dms ip=%s user=%s rid=%s", request.method, service, path, status,
                    int((time.monotonic() - t0) * 1000), _client_ip(request), user, rid)
