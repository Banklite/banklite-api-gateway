"""Pruebas UNITARIAS de las reglas del gateway: rutas publicas, rutas sensibles e IP del cliente."""
from unittest.mock import Mock

import pytest

from app import main


@pytest.mark.parametrize("metodo, ruta", [
    ("POST", "identity/auth/login"),
    ("POST", "identity/users"),
])
def test_rutas_publicas_no_exigen_token(metodo, ruta):
    assert main._is_public(metodo, ruta) is True


@pytest.mark.parametrize("metodo, ruta", [
    ("GET", "identity/users"),            # listar usuarios si exige sesion
    ("POST", "transfer/transfers"),
    ("GET", "ledger/ledger/accounts/123"),
    ("DELETE", "card/cards/123"),
])
def test_el_resto_de_rutas_exige_token(metodo, ruta):
    assert main._is_public(metodo, ruta) is False


@pytest.mark.parametrize("ruta, sensible", [
    ("identity/auth/login", True),
    ("identity/auth/otp/validar", True),
    ("identity/auth/pin/login", True),
    ("identity/auth/reset-clave", True),
    ("identity/users/abc-123/cambiar-clave", True),
    ("identity/users/abc-123", False),
    ("transfer/transfers", False),
])
def test_las_rutas_de_credenciales_tienen_limite_estricto(ruta, sensible):
    assert bool(main._SENSITIVE.match(ruta)) is sensible


def test_la_ip_del_cliente_sale_de_x_forwarded_for_cuando_hay_proxy():
    detras_de_proxy = Mock(headers={"x-forwarded-for": "190.25.10.7, 10.0.0.1"}, client=Mock(host="10.0.0.1"))
    directo = Mock(headers={}, client=Mock(host="186.30.1.9"))

    assert main._client_ip(detras_de_proxy) == "190.25.10.7"
    assert main._client_ip(directo) == "186.30.1.9"
