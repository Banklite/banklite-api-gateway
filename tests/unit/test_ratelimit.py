"""Pruebas UNITARIAS del limitador de peticiones (ventana deslizante).

El reloj se reemplaza con un mock para mover el tiempo sin esperar de verdad.
"""
from unittest.mock import patch

from app.ratelimit import RateLimiter


def test_permite_hasta_el_limite_y_bloquea_la_siguiente():
    limitador = RateLimiter()
    with patch("app.ratelimit.time.monotonic", return_value=1000.0):
        resultados = [limitador.check("ip-1", limit=3) for _ in range(4)]

    assert [permitido for permitido, _ in resultados] == [True, True, True, False]
    assert resultados[3][1] == 61  # segundos que debe esperar el cliente (cabecera Retry-After)


def test_cada_cliente_tiene_su_propio_contador():
    limitador = RateLimiter()
    with patch("app.ratelimit.time.monotonic", return_value=1000.0):
        limitador.check("ip-1", limit=1)
        assert limitador.check("ip-1", limit=1)[0] is False
        assert limitador.check("ip-2", limit=1)[0] is True


def test_la_ventana_se_desliza_y_vuelve_a_permitir():
    limitador = RateLimiter()
    with patch("app.ratelimit.time.monotonic") as reloj:
        reloj.return_value = 1000.0
        limitador.check("ip-1", limit=2)
        reloj.return_value = 1030.0
        limitador.check("ip-1", limit=2)
        assert limitador.check("ip-1", limit=2) == (False, 31)   # falta que venza la primera peticion

        reloj.return_value = 1060.0                               # la primera ya salio de la ventana
        assert limitador.check("ip-1", limit=2) == (True, 0)
        assert limitador.check("ip-1", limit=2)[0] is False       # la de 1030 sigue contando


def test_reset_borra_todos_los_contadores():
    limitador = RateLimiter()
    with patch("app.ratelimit.time.monotonic", return_value=1000.0):
        limitador.check("ip-1", limit=1)
        limitador.reset()
        assert limitador.check("ip-1", limit=1)[0] is True
