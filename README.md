# API Gateway — BankLite

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
| **Salud agregada** | `GET /health/all` consulta los 8 servicios en paralelo; sirve para despertarlos en Render gratis. |

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
python -m pytest -q tests           # 10 pruebas
uvicorn app.main:app --reload --port 8000
```

Docker: `docker build -t banklite-api-gateway . && docker run --env-file .env -p 8000:8000 banklite-api-gateway`

Documentacion: `/docs`. El gateway no tiene base de datos propia (no guarda estado; el rate limiting vive en memoria).

## Conectar el panel web

En Vercel, apunta cada variable al gateway y vuelve a desplegar:

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
