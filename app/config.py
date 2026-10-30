from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "api-gateway"
    api_port: int = 8000

    # Debe ser EL MISMO secreto con el que identity-service firma los JWT.
    jwt_secret: str = "banklite-dev-secret-cambiar-en-produccion"
    jwt_algorithm: str = "HS256"

    # URL de cada microservicio (el gateway enruta /<nombre>/... hacia ellas).
    identity_service_url: str = "http://identity-service:8001"
    account_service_url: str = "http://account-service:8002"
    ledger_service_url: str = "http://ledger-service:8003"
    transfer_service_url: str = "http://transfer-service:8004"
    card_service_url: str = "http://card-service:8005"
    fraud_service_url: str = "http://fraud-service:8006"
    notification_service_url: str = "http://notification-service:8007"
    compliance_service_url: str = "http://compliance-service:8008"

    # Un servicio dormido (Render gratis) puede tardar ~50 s en despertar.
    upstream_timeout_seconds: float = 90.0

    # /health/all: reintentos mientras un servicio dormido arranca (8 x 6 s ~ 48 s).
    health_retries: int = 8
    health_retry_delay_seconds: float = 6.0

    # Autenticacion: si es false, el gateway enruta sin exigir JWT (solo para depurar).
    auth_enforce: bool = True
    # Rutas (prefijos, sin el nombre del servicio) que exigen rol admin.
    admin_prefixes: str = "compliance/,analytics/"

    # Rate limiting en memoria, por IP: ventana de 60 s.
    rate_limit_per_minute: int = 240
    rate_limit_sensitive_per_minute: int = 15

    @property
    def upstreams(self) -> dict[str, str]:
        return {
            "identity": self.identity_service_url,
            "account": self.account_service_url,
            "ledger": self.ledger_service_url,
            "transfer": self.transfer_service_url,
            "card": self.card_service_url,
            "fraud": self.fraud_service_url,
            "notification": self.notification_service_url,
            "compliance": self.compliance_service_url,
        }


settings = Settings()
