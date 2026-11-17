# API Gateway — BankLite

[![CI](https://github.com/Banklite/banklite-api-gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/Banklite/banklite-api-gateway/actions/workflows/ci.yml)
[![Deploy](https://github.com/Banklite/banklite-api-gateway/actions/workflows/deploy.yml/badge.svg)](https://github.com/Banklite/banklite-api-gateway/actions/workflows/deploy.yml)

Punto unico de entrada al backend de BankLite. El cliente (panel web) habla solo con el gateway; el gateway valida la sesion y reenvia la peticion al microservicio correcto.

Parte del proyecto **BankLite** de *Arquitectura y Modelamiento de Software*, Universidad Cooperativa de Colombia.

## Funciones

| Funcion | Como se implementa |
|---|---|
| **Autenticacion JWT** | Valida el token `Bearer` que emite `identity-service` (mismo `JWT_SECRET`). El token se entrega despues del segundo factor (codigo por correo / PIN), asi que el gateway solo deja pasar sesiones con MFA completado. |
| **Autorizacion por rol** | Las rutas de `compliance/` y `analytics/` exigen `role=admin` en el token (`ADMIN_PREFIXES`). |
| **Rate limiting** | Ventana de 60 s por IP: 240 peticiones/min en general y 15/min en login, OTP, PIN y cambio de clave (frena fuerza bruta). Responde `429` con `Retry-After`. |
| **Enrutamiento** | `/<servicio>/<ruta>` → `<URL del servicio>/<ruta>`. |
| **Logging** | Una linea por peticion: metodo, ruta, estado, milisegundos, IP, usuario y `X-Request-ID` (que tambien viaja al microservicio). |
| **Salud agregada** | `GET /health/all` consulta los 8 servicios en paralelo y reintenta (hasta ~48 s) mientras los dormidos de Render gratis despiertan. |

Comunicacion: REST. Los microservicios siguen hablando entre si directamente (REST y eventos en RabbitMQ), sin pasar por el gateway.

## Ruteo

| Prefijo | Microservicio |
|---|---|
| `/identity/...` | identity-service |
| `/account/...` | account-service |
| `/ledger/...` | ledger-service |
| `/transfer/...` | transfer-service |
| `/card/...` | card-service |
| `/fraud/...` | fraud-service |
| `/notification/...` | notification-service |
| `/compliance/...` | compliance-service |

Ejemplo: `GET /transfer/transfers/trm` llega a transfer-service como `GET /transfers/trm`.

### Rutas publicas (sin token)

Registro (`POST /identity/users`, `POST /identity/kyc/verify`), validacion de identidad, ciudades, login (`/identity/auth/login`, solicitar y confirmar codigo, reset de clave, PIN), cotizacion publica (`/transfer/transfers/trm`, `/divisas`), puntos de cajero y `/health` de cada servicio. Todo lo demas exige token.

## Errores del gateway

| Codigo | Causa |
|---|---|
| 401 | Falta el token, es invalido o esta vencido |
| 403 | La ruta requiere rol administrador |
| 404 | Servicio desconocido |
| 429 | Limite de peticiones superado |
| 502 / 504 | El microservicio no responde (en Render gratis puede estar despertando: reintentar) |

## Variables de entorno

Ver `.env.example`.

| Variable | Descripcion |
|---|---|
| `JWT_SECRET` | Secreto de firma; debe ser igual al de identity-service |
| `AUTH_ENFORCE` | `false` desactiva la exigencia de token (solo para depurar) |
| `ADMIN_PREFIXES` | Prefijos que exigen rol admin |
| `RATE_LIMIT_PER_MINUTE` / `RATE_LIMIT_SENSITIVE_PER_MINUTE` | Limites por IP |
| `UPSTREAM_TIMEOUT_SECONDS` | Espera maxima a un microservicio (90 por los arranques en frio) |
| `*_SERVICE_URL` | URL de cada microservicio |

## Ejecucion

```bash
pip install -r requirements.txt
python -m pytest -q tests           # 12 pruebas
uvicorn app.main:app --reload --port 8000
```

Docker: `docker build -t banklite-api-gateway . && docker run --env-file .env -p 8000:8000 banklite-api-gateway`

Documentacion: `/docs`. El gateway no tiene base de datos propia (no guarda estado; el rate limiting vive en memoria).

## Pruebas automatizadas

```bash
pip install -r requirements-dev.txt
python -m pytest tests -v --cov=app --cov-report=term-missing --cov-report=html
```

No necesitan PostgreSQL, RabbitMQ ni los otros microservicios: la base es SQLite en memoria y las dependencias externas se reemplazan con mocks (`unittest.mock`). El reporte navegable queda en `htmlcov/index.html`.

| Tipo | Archivo | Que verifica |
|---|---|---|
| Unitaria (mocks) | `tests/unit/test_ratelimit.py` | Limitador de peticiones por ventana deslizante, con el reloj simulado. |
| Unitaria | `tests/unit/test_reglas_de_ruteo.py` | Que rutas son publicas, cuales son sensibles (limite estricto) y como se obtiene la IP del cliente. |
| Integracion | `tests/integration/test_gateway.py` | Gateway completo con los microservicios simulados (`httpx.MockTransport`): JWT, rol admin, ruteo, rate limit y `/health/all`. |
| Integracion | `tests/integration/test_metrics.py` | `GET /metrics` cuenta las peticiones por ruta y codigo de estado, publica la latencia y no se cuenta a si mismo. |

Resultado actual: **35 pruebas** (18 unitarias y 17 de integracion), todas aprobadas, con **95 % de cobertura** de `app/`. El pipeline exige un minimo de 70 %.

## Monitoreo con Prometheus y Grafana

El servicio expone sus metricas en `GET /metrics` (libreria `prometheus-client`, modulo `app/metrics.py`):

| Senal | Metrica | Tipo |
|---|---|---|
| Trafico | `http_requests_total{method, path, status}` | Counter |
| Errores | `http_requests_total{status=~"5.."}` | Counter |
| Latencia | `http_request_duration_seconds` | Histogram |
| Saturacion | `http_requests_in_progress`, `process_resident_memory_bytes` | Gauge |

La etiqueta `path` es el microservicio de destino (por ejemplo `/identity`), no la URL completa: asi un id distinto no crea una serie nueva.

La configuracion esta versionada en `monitoring/`:

| Archivo | Para que sirve |
|---|---|
| `prometheus.yml` | A quien consulta Prometheus y cada cuanto (15 s) |
| `alertas.yml` | Alertas: servicio caido, mas de 5 % de errores 5xx, latencia p95 mayor a 1 s |
| `docker-compose.yml` | Levanta Prometheus y Grafana |
| `grafana/dashboards/banklite.json` | Dashboard con disponibilidad, peticiones, tiempos de respuesta y tasa de errores |
| `grafana/provisioning/` | Conecta Grafana con Prometheus y carga el dashboard al arrancar |

```bash
cd monitoring
docker compose up -d
```

- Prometheus: <http://localhost:9090> — en *Status > Targets* el servicio debe aparecer en **UP**.
- Grafana: <http://localhost:3000> (usuario `admin`, clave `admin`) — carpeta *BankLite*, dashboard *Cuatro senales doradas*.

`monitoring/prometheus.yml` consulta a los ocho microservicios, asi que este es el tablero del sistema completo. Para incluir al propio gateway, descomenta su bloque y pon su host publico de Render. El gateway etiqueta el trafico por microservicio de destino (`path="/identity"`, `path="/transfer"`...).

Render (plan gratuito) duerme el servicio tras 15 minutos sin trafico. La primera consulta lo despierta y puede tardar cerca de un minuto, por eso el target puede verse en DOWN al comienzo. Mientras Prometheus este encendido el servicio no se duerme y consume horas del plan: apaga el stack con `docker compose down` cuando termines.

## CI/CD y estrategia de ramas

Los workflows estan en `.github/workflows/`:

| Archivo | Cuando corre | Que hace |
|---|---|---|
| `ci.yml` | Cada `push` a una rama y cada `pull request` hacia `main` | Instala dependencias, compila, ejecuta las pruebas unitarias y de integracion, mide la cobertura (minimo 70 %), sube el reporte como artefacto `coverage-banklite-api-gateway` y comprueba que la imagen Docker construye |
| `deploy.yml` | Cada cambio integrado en `main` (o a mano) | Ejecuta `ci.yml`; si pasa, publica la imagen en GitHub Container Registry y pide el despliegue a Render |

Los jobs de `deploy.yml` estan encadenados con `needs`: si una sola prueba falla, no se construye la imagen ni se despliega. El Deploy Hook de Render es una credencial y esta en *Settings > Secrets and variables > Actions* como `RENDER_DEPLOY_HOOK_URL`; si falta, el despliegue falla en vez de terminar en verde sin desplegar.

Estrategia de ramas:

1. `main` es la rama desplegada. No se trabaja directamente sobre ella.
2. Cada cambio se hace en una rama corta (`feat/...`, `fix/...`, `test/...`). Cada `push` ejecuta `ci.yml`.
3. Se abre un pull request hacia `main`. El check de CI debe estar en verde para fusionar.
4. Al fusionar, `deploy.yml` vuelve a ejecutar las pruebas y despliega.

## Conectar el panel web

En Render, en las variables de entorno del panel, apunta cada variable al gateway y vuelve a desplegar:

```
NEXT_PUBLIC_IDENTITY_API_URL=https://<gateway>/identity
NEXT_PUBLIC_ACCOUNT_API_URL=https://<gateway>/account
NEXT_PUBLIC_LEDGER_API_URL=https://<gateway>/ledger
NEXT_PUBLIC_TRANSFER_API_URL=https://<gateway>/transfer
NEXT_PUBLIC_CARD_API_URL=https://<gateway>/card
NEXT_PUBLIC_FRAUD_API_URL=https://<gateway>/fraud
NEXT_PUBLIC_NOTIFICATION_API_URL=https://<gateway>/notification
NEXT_PUBLIC_COMPLIANCE_API_URL=https://<gateway>/compliance
```
