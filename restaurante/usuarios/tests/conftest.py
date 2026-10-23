import os

# Las variables deben existir antes de importar la aplicación.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "secreto-solo-para-pruebas-0123456789abcdef"
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["ADMIN_EMAIL"] = "admin@restaurante.test"
os.environ["ADMIN_PASSWORD"] = "ClaveAdmin123"

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import sembrar_datos
from app.database import Base, SessionLocal, engine
from app.main import app


@pytest.fixture(autouse=True)
def base_de_datos():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        sembrar_datos(db)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    return TestClient(app)


def _login(client, email, password):
    return client.post("/usuarios/login", json={"email": email, "password": password})


@pytest.fixture
def token_admin(client):
    return _login(client, "admin@restaurante.test", "ClaveAdmin123").json()["access_token"]


@pytest.fixture
def cabecera_admin(token_admin):
    return {"Authorization": f"Bearer {token_admin}"}


@pytest.fixture
def crear_usuario(client, cabecera_admin):
    def _crear(email="mesero@restaurante.test", rol="MESERO", password="ClaveMesero1"):
        respuesta = client.post(
            "/usuarios",
            json={"nombre": "Persona de prueba", "email": email, "password": password, "rol": rol},
            headers=cabecera_admin,
        )
        assert respuesta.status_code == 201, respuesta.text
        return respuesta.json()

    return _crear


@pytest.fixture
def cabecera_de(client, crear_usuario):
    def _cabecera(rol, email=None):
        email = email or f"{rol.lower()}@restaurante.test"
        crear_usuario(email=email, rol=rol, password="ClaveSegura1")
        token = _login(client, email, "ClaveSegura1").json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    return _cabecera
