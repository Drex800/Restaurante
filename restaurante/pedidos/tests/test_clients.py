"""Pruebas del cliente HTTP hacia productos, con un transporte simulado."""

import httpx
import pytest

from app.clients import (
    ProductosClient,
    ProductosNoDisponible,
    StockInsuficiente,
    get_productos_client,
)


def cliente_con(respuesta_o_error):
    def manejador(peticion: httpx.Request) -> httpx.Response:
        manejador.ultima = peticion
        if isinstance(respuesta_o_error, Exception):
            raise respuesta_o_error
        return respuesta_o_error

    manejador.ultima = None
    cliente = ProductosClient(
        base_url="http://productos:8000",
        service_token="token-x",
        transport=httpx.MockTransport(manejador),
    )
    return cliente, manejador


def test_obtener_producto_reenvia_el_token_del_usuario():
    cliente, manejador = cliente_con(httpx.Response(200, json={"id": 1, "nombre": "Sopa"}))
    producto = cliente.obtener_producto(1, "Bearer abc")
    assert producto == {"id": 1, "nombre": "Sopa"}
    assert manejador.ultima.url.path == "/productos/1"
    assert manejador.ultima.headers["authorization"] == "Bearer abc"


def test_obtener_producto_inexistente_devuelve_none():
    cliente, _ = cliente_con(httpx.Response(404, json={"detail": "no"}))
    assert cliente.obtener_producto(1, "Bearer abc") is None


@pytest.mark.parametrize("codigo", [401, 403, 500])
def test_obtener_producto_con_error_lanza_no_disponible(codigo):
    cliente, _ = cliente_con(httpx.Response(codigo))
    with pytest.raises(ProductosNoDisponible):
        cliente.obtener_producto(1, "Bearer abc")


def test_obtener_producto_sin_conexion():
    cliente, _ = cliente_con(httpx.ConnectError("sin red"))
    with pytest.raises(ProductosNoDisponible):
        cliente.obtener_producto(1, "Bearer abc")


def test_registrar_movimiento_envia_el_token_de_servicio():
    cliente, manejador = cliente_con(httpx.Response(201, json={}))
    cliente.registrar_movimiento(7, "SALIDA", 2, "Pedido #1")
    assert manejador.ultima.method == "POST"
    assert manejador.ultima.url.path == "/productos/7/movimientos"
    assert manejador.ultima.headers["x-service-token"] == "token-x"


def test_registrar_movimiento_sin_stock():
    cliente, _ = cliente_con(httpx.Response(409, json={"detail": "Stock insuficiente: hay 1"}))
    with pytest.raises(StockInsuficiente, match="hay 1"):
        cliente.registrar_movimiento(7, "SALIDA", 2, "Pedido #1")


def test_registrar_movimiento_con_error_inesperado():
    cliente, _ = cliente_con(httpx.Response(500))
    with pytest.raises(ProductosNoDisponible):
        cliente.registrar_movimiento(7, "SALIDA", 2, "Pedido #1")


def test_registrar_movimiento_sin_conexion():
    cliente, _ = cliente_con(httpx.ConnectError("sin red"))
    with pytest.raises(ProductosNoDisponible):
        cliente.registrar_movimiento(7, "SALIDA", 2, "Pedido #1")


def test_valores_por_defecto_vienen_del_entorno(monkeypatch):
    monkeypatch.setenv("PRODUCTOS_URL", "http://otro:9000")
    monkeypatch.setenv("SERVICE_TOKEN", "desde-entorno")
    cliente = get_productos_client()
    assert cliente.base_url == "http://otro:9000"
    assert cliente.service_token == "desde-entorno"
