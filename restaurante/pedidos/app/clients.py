"""Cliente HTTP hacia el servicio de productos (por la red privada, sin pasar por Kong).

Este servicio nunca lee la base de datos de productos: le pregunta a su API.
"""

import os

import httpx


class ProductosNoDisponible(Exception):
    """El servicio de productos no respondió como se esperaba."""


class StockInsuficiente(Exception):
    """El servicio de productos rechazó la salida por falta de stock."""


class ProductosClient:
    def __init__(
        self,
        base_url: str | None = None,
        service_token: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url or os.environ.get("PRODUCTOS_URL", "http://productos:8000")
        self.service_token = service_token or os.environ.get("SERVICE_TOKEN", "")
        self._transport = transport

    def _cliente(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=5.0, transport=self._transport)

    def obtener_producto(self, producto_id: int, authorization: str) -> dict | None:
        """Devuelve el producto (con precio y stock) o None si no existe."""
        try:
            with self._cliente() as cliente:
                respuesta = cliente.get(
                    f"/productos/{producto_id}", headers={"Authorization": authorization}
                )
        except httpx.HTTPError as exc:
            raise ProductosNoDisponible("No se pudo consultar el servicio de productos") from exc
        if respuesta.status_code == 404:
            return None
        if respuesta.status_code != 200:
            raise ProductosNoDisponible(f"Productos respondió {respuesta.status_code}")
        return respuesta.json()

    def registrar_movimiento(
        self, producto_id: int, tipo: str, cantidad: int, motivo: str
    ) -> None:
        try:
            with self._cliente() as cliente:
                respuesta = cliente.post(
                    f"/productos/{producto_id}/movimientos",
                    json={"tipo": tipo, "cantidad": cantidad, "motivo": motivo},
                    headers={"X-Service-Token": self.service_token},
                )
        except httpx.HTTPError as exc:
            raise ProductosNoDisponible("No se pudo consultar el servicio de productos") from exc
        if respuesta.status_code == 409:
            raise StockInsuficiente(respuesta.json().get("detail", "Stock insuficiente"))
        if respuesta.status_code != 201:
            raise ProductosNoDisponible(f"Productos respondió {respuesta.status_code}")


def get_productos_client() -> ProductosClient:
    """Dependencia de FastAPI; las pruebas la reemplazan por un doble."""
    return ProductosClient()
