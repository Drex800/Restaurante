from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app import bootstrap, routes
from app.database import SessionLocal
from app.models import Usuario


# ---------- health ----------
def test_health_ok(client):
    r = client.get("/usuarios/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_503_si_la_base_falla(client, monkeypatch):
    class MotorRoto:
        def connect(self):
            raise SQLAlchemyError("sin conexión")

    monkeypatch.setattr(routes, "engine", MotorRoto())
    assert client.get("/usuarios/health").status_code == 503


# ---------- login ----------
def test_login_correcto_devuelve_token_con_rol(client):
    r = client.post(
        "/usuarios/login",
        json={"email": "admin@restaurante.test", "password": "ClaveAdmin123"},
    )
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["token_type"] == "bearer"
    carga = jwt.decode(
        cuerpo["access_token"],
        "secreto-solo-para-pruebas-0123456789abcdef",
        algorithms=["HS256"],
    )
    assert carga["rol"] == "ADMIN"


def test_login_con_clave_incorrecta(client):
    r = client.post(
        "/usuarios/login",
        json={"email": "admin@restaurante.test", "password": "incorrecta"},
    )
    assert r.status_code == 401


def test_login_con_usuario_inexistente(client):
    r = client.post(
        "/usuarios/login",
        json={"email": "nadie@restaurante.test", "password": "ClaveAdmin123"},
    )
    assert r.status_code == 401


def test_login_con_correo_mal_formado(client):
    r = client.post("/usuarios/login", json={"email": "no-es-correo", "password": "x"})
    assert r.status_code == 422


# ---------- /me y validación del token ----------
def test_me_sin_token(client):
    assert client.get("/usuarios/me").status_code == 401


def test_me_con_token_invalido(client):
    r = client.get("/usuarios/me", headers={"Authorization": "Bearer basura"})
    assert r.status_code == 401


def test_me_con_token_firmado_con_otra_clave(client):
    falso = jwt.encode(
        {"sub": "1", "rol": "ADMIN", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        "otra-clave-distinta-de-32-caracteres-xx",
        algorithm="HS256",
    )
    r = client.get("/usuarios/me", headers={"Authorization": f"Bearer {falso}"})
    assert r.status_code == 401


def test_me_con_token_vencido(client):
    vencido = jwt.encode(
        {"sub": "1", "rol": "ADMIN", "exp": datetime.now(UTC) - timedelta(minutes=5)},
        "secreto-solo-para-pruebas-0123456789abcdef",
        algorithm="HS256",
    )
    r = client.get("/usuarios/me", headers={"Authorization": f"Bearer {vencido}"})
    assert r.status_code == 401


def test_me_devuelve_el_usuario(client, cabecera_admin):
    r = client.get("/usuarios/me", headers=cabecera_admin)
    assert r.status_code == 200
    assert r.json()["email"] == "admin@restaurante.test"
    assert r.json()["rol"] == "ADMIN"


# ---------- gestión de usuarios (solo administrador) ----------
def test_admin_crea_usuario(client, crear_usuario):
    creado = crear_usuario(email="cocina@restaurante.test", rol="COCINA")
    assert creado["rol"] == "COCINA"
    assert creado["activo"] is True
    assert "password" not in creado


def test_no_se_repite_el_correo(client, crear_usuario, cabecera_admin):
    crear_usuario(email="repetido@restaurante.test")
    r = client.post(
        "/usuarios",
        json={
            "nombre": "Otro",
            "email": "repetido@restaurante.test",
            "password": "ClaveMesero1",
            "rol": "MESERO",
        },
        headers=cabecera_admin,
    )
    assert r.status_code == 409


def test_rol_inexistente_es_422(client, cabecera_admin):
    r = client.post(
        "/usuarios",
        json={"nombre": "X", "email": "x@restaurante.test", "password": "ClaveMesero1", "rol": "DUENO"},
        headers=cabecera_admin,
    )
    assert r.status_code == 422


def test_clave_corta_es_422(client, cabecera_admin):
    r = client.post(
        "/usuarios",
        json={"nombre": "X", "email": "x@restaurante.test", "password": "corta", "rol": "MESERO"},
        headers=cabecera_admin,
    )
    assert r.status_code == 422


@pytest.mark.parametrize("rol", ["MESERO", "COCINA", "CAJERO"])
def test_otros_roles_no_pueden_gestionar_usuarios(client, cabecera_de, rol):
    cabecera = cabecera_de(rol)
    assert client.get("/usuarios", headers=cabecera).status_code == 403
    assert client.get("/usuarios/1", headers=cabecera).status_code == 403
    r = client.post(
        "/usuarios",
        json={"nombre": "X", "email": "x@restaurante.test", "password": "ClaveMesero1", "rol": "MESERO"},
        headers=cabecera,
    )
    assert r.status_code == 403
    assert client.delete("/usuarios/1", headers=cabecera).status_code == 403


def test_admin_lista_y_obtiene(client, crear_usuario, cabecera_admin):
    creado = crear_usuario()
    lista = client.get("/usuarios", headers=cabecera_admin).json()
    assert {u["email"] for u in lista} == {"admin@restaurante.test", "mesero@restaurante.test"}
    uno = client.get(f"/usuarios/{creado['id']}", headers=cabecera_admin)
    assert uno.status_code == 200
    assert uno.json()["email"] == "mesero@restaurante.test"


def test_obtener_inexistente_es_404(client, cabecera_admin):
    assert client.get("/usuarios/9999", headers=cabecera_admin).status_code == 404


def test_desactivar_impide_el_login(client, crear_usuario, cabecera_admin):
    creado = crear_usuario()
    r = client.delete(f"/usuarios/{creado['id']}", headers=cabecera_admin)
    assert r.status_code == 204
    login = client.post(
        "/usuarios/login",
        json={"email": "mesero@restaurante.test", "password": "ClaveMesero1"},
    )
    assert login.status_code == 401


def test_admin_no_puede_desactivarse(client, cabecera_admin):
    yo = client.get("/usuarios/me", headers=cabecera_admin).json()
    r = client.delete(f"/usuarios/{yo['id']}", headers=cabecera_admin)
    assert r.status_code == 400


def test_desactivar_inexistente_es_404(client, cabecera_admin):
    assert client.delete("/usuarios/9999", headers=cabecera_admin).status_code == 404


def test_la_clave_se_guarda_cifrada(client, crear_usuario):
    crear_usuario()
    with SessionLocal() as db:
        usuario = db.query(Usuario).filter_by(email="mesero@restaurante.test").one()
    assert usuario.password_hash != "ClaveMesero1"
    assert usuario.password_hash.startswith("$2")


# ---------- arranque ----------
def test_sembrar_datos_es_idempotente():
    with SessionLocal() as db:
        bootstrap.sembrar_datos(db)
        bootstrap.sembrar_datos(db)
        assert db.query(Usuario).filter_by(email="admin@restaurante.test").count() == 1


def test_sin_variables_de_admin_no_se_crea_administrador(monkeypatch):
    with SessionLocal() as db:
        db.query(Usuario).delete()
        db.commit()
        monkeypatch.delenv("ADMIN_EMAIL")
        monkeypatch.delenv("ADMIN_PASSWORD")
        bootstrap.sembrar_datos(db)
        assert db.query(Usuario).count() == 0


def test_crear_tablas_reintenta_si_la_base_no_esta_lista(monkeypatch):
    llamadas = {"n": 0}

    def inestable(_motor):
        llamadas["n"] += 1
        if llamadas["n"] < 3:
            raise OperationalError("conexión", {}, Exception("aún no"))

    monkeypatch.setattr(bootstrap.Base.metadata, "create_all", inestable)
    monkeypatch.setattr(bootstrap.time, "sleep", lambda _s: None)
    bootstrap.crear_tablas(intentos=5, espera=0)
    assert llamadas["n"] == 3


def test_crear_tablas_falla_tras_agotar_intentos(monkeypatch):
    def roto(_motor):
        raise OperationalError("conexión", {}, Exception("caída"))

    monkeypatch.setattr(bootstrap.Base.metadata, "create_all", roto)
    monkeypatch.setattr(bootstrap.time, "sleep", lambda _s: None)
    with pytest.raises(OperationalError):
        bootstrap.crear_tablas(intentos=2, espera=0)


def test_el_arranque_de_la_app_crea_tablas_y_admin():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as cliente:
        assert cliente.get("/usuarios/health").status_code == 200
