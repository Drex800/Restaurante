import os

# Las variables deben existir antes de importar la aplicación.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "secreto-solo-para-pruebas-0123456789abcdef"
os.environ["SERVICE_TOKEN"] = "token-de-servicio-solo-para-pruebas"

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from app.clients import ProductosNoDisponible, StockInsuficiente, get_productos_client
from app.database import Base, engine
from app.main import app


class ProductosFalso:
    """Doble del servicio de productos: catálogo y stock en memoria."""

    def __init__(self):
        self.catalogo = {
            1: {"id": 1, "nombre": "Bandeja paisa", "precio": 32000.0, "activo": True, "stock": 10},
            2: {"id": 2, "nombre": "Jugo de lulo", "precio": 6500.5, "activo": True, "stock": 5},
            3: {"id": 3, "nombre": "Sopa agotada", "precio": 9000.0, "activo": True, "stock": 0},
            4: {"id": 4, "nombre": "Plato retirado", "precio": 9000.0, "activo": False, "stock": 9},
        }
        self.movimientos = []
        self.caido = False
        self.fallar_salida_del_producto = None

    def obtener_producto(self, producto_id, authorization):
        assert authorization.startswith("Bearer ")
        if self.caido:
            raise ProductosNoDisponible("caído")
        return self.catalogo.get(producto_id)

    def registrar_movimiento(self, producto_id, tipo, cantidad, motivo):
        if self.caido:
            raise ProductosNoDisponible("caído")
        if tipo == "SALIDA" and producto_id == self.fallar_salida_del_producto:
            raise StockInsuficiente("Stock insuficiente")
        efecto = -cantidad if tipo == "SALIDA" else cantidad
        self.catalogo[producto_id]["stock"] += efecto
        self.movimientos.append((producto_id, tipo, cantidad, motivo))


@pytest.fixture(autouse=True)
def base_de_datos():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def productos():
    return ProductosFalso()


@pytest.fixture
def client(productos):
    app.dependency_overrides[get_productos_client] = lambda: productos
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def cabecera():
    """Fabrica la cabecera Authorization de un usuario con el rol indicado."""

    def _cabecera(rol, usuario_id=1):
        token = jwt.encode(
            {
                "sub": str(usuario_id),
                "rol": rol,
                "exp": datetime.now(UTC) + timedelta(minutes=10),
            },
            os.environ["JWT_SECRET"],
            algorithm="HS256",
        )
        return {"Authorization": f"Bearer {token}"}

    return _cabecera


@pytest.fixture
def admin(cabecera):
    return cabecera("ADMIN", usuario_id=1)


@pytest.fixture
def mesero(cabecera):
    return cabecera("MESERO", usuario_id=10)


@pytest.fixture
def cocina(cabecera):
    return cabecera("COCINA", usuario_id=20)


@pytest.fixture
def cajero(cabecera):
    return cabecera("CAJERO", usuario_id=30)


@pytest.fixture
def mesa(client, admin):
    r = client.post("/pedidos/mesas", json={"numero": 5, "capacidad": 4}, headers=admin)
    assert r.status_code == 201
    return r.json()


@pytest.fixture
def pedido(client, mesero, mesa):
    """Un pedido de 2 bandejas y 1 jugo: total 70.500,50."""
    r = client.post(
        "/pedidos",
        json={
            "mesa_id": mesa["id"],
            "items": [
                {"producto_id": 1, "cantidad": 2, "nota": "sin cebolla"},
                {"producto_id": 2, "cantidad": 1},
            ],
        },
        headers=mesero,
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def pedido_listo(client, pedido, cocina):
    for nuevo in ("EN_PREPARACION", "LISTO"):
        r = client.patch(f"/pedidos/{pedido['id']}/estado", json={"estado": nuevo}, headers=cocina)
        assert r.status_code == 200, r.text
    return r.json()
