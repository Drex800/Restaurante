import os

# Las variables deben existir antes de importar la aplicación.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "secreto-solo-para-pruebas-0123456789abcdef"
os.environ["SERVICE_TOKEN"] = "token-de-servicio-solo-para-pruebas"

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def base_de_datos():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    return TestClient(app)


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
    return cabecera("ADMIN")


@pytest.fixture
def categoria(client, admin):
    r = client.post("/productos/categorias", json={"nombre": "Platos fuertes"}, headers=admin)
    assert r.status_code == 201
    return r.json()


@pytest.fixture
def producto(client, admin, categoria):
    r = client.post(
        "/productos",
        json={"nombre": "Bandeja paisa", "precio": 32000, "categoria_id": categoria["id"]},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    return r.json()
