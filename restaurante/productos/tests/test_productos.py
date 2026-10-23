import pytest
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app import bootstrap, routes

SERVICIO = {"X-Service-Token": "token-de-servicio-solo-para-pruebas"}


# ---------- health ----------
def test_health_ok(client):
    r = client.get("/productos/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_503_si_la_base_falla(client, monkeypatch):
    class MotorRoto:
        def connect(self):
            raise SQLAlchemyError("sin conexión")

    monkeypatch.setattr(routes, "engine", MotorRoto())
    assert client.get("/productos/health").status_code == 503


# ---------- autenticación ----------
def test_listar_requiere_token(client):
    assert client.get("/productos").status_code == 401


def test_token_invalido(client):
    r = client.get("/productos", headers={"Authorization": "Bearer basura"})
    assert r.status_code == 401


# ---------- categorías ----------
def test_admin_crea_y_lista_categorias(client, admin, categoria):
    r = client.get("/productos/categorias", headers=admin)
    assert r.status_code == 200
    assert [c["nombre"] for c in r.json()] == ["Platos fuertes"]


def test_categoria_repetida_es_409(client, admin, categoria):
    r = client.post("/productos/categorias", json={"nombre": "Platos fuertes"}, headers=admin)
    assert r.status_code == 409


def test_mesero_no_crea_categorias(client, cabecera):
    r = client.post("/productos/categorias", json={"nombre": "Bebidas"}, headers=cabecera("MESERO"))
    assert r.status_code == 403


def test_mesero_si_lista_categorias(client, cabecera, categoria):
    r = client.get("/productos/categorias", headers=cabecera("MESERO"))
    assert r.status_code == 200
    assert len(r.json()) == 1


# ---------- productos ----------
def test_crear_producto(client, producto):
    assert producto["nombre"] == "Bandeja paisa"
    assert producto["precio"] == 32000
    assert producto["stock"] == 0
    assert producto["activo"] is True


def test_crear_producto_con_categoria_inexistente(client, admin):
    r = client.post(
        "/productos",
        json={"nombre": "Sopa", "precio": 8000, "categoria_id": 999},
        headers=admin,
    )
    assert r.status_code == 404


@pytest.mark.parametrize("precio", [0, -5])
def test_precio_debe_ser_positivo(client, admin, categoria, precio):
    r = client.post(
        "/productos",
        json={"nombre": "Sopa", "precio": precio, "categoria_id": categoria["id"]},
        headers=admin,
    )
    assert r.status_code == 422


def test_solo_admin_crea_productos(client, cabecera, categoria):
    for rol in ("MESERO", "COCINA", "CAJERO"):
        r = client.post(
            "/productos",
            json={"nombre": "Sopa", "precio": 8000, "categoria_id": categoria["id"]},
            headers=cabecera(rol),
        )
        assert r.status_code == 403


def test_listar_filtra_por_categoria_y_oculta_inactivos(client, admin, cabecera, producto):
    otra = client.post("/productos/categorias", json={"nombre": "Bebidas"}, headers=admin).json()
    jugo = client.post(
        "/productos",
        json={"nombre": "Jugo de lulo", "precio": 6000, "categoria_id": otra["id"]},
        headers=admin,
    ).json()
    mesero = cabecera("MESERO")

    todos = client.get("/productos", headers=mesero).json()
    assert {p["nombre"] for p in todos} == {"Bandeja paisa", "Jugo de lulo"}

    solo_bebidas = client.get(f"/productos?categoria_id={otra['id']}", headers=mesero).json()
    assert [p["nombre"] for p in solo_bebidas] == ["Jugo de lulo"]

    assert client.delete(f"/productos/{jugo['id']}", headers=admin).status_code == 204
    activos = client.get("/productos", headers=mesero).json()
    assert [p["nombre"] for p in activos] == ["Bandeja paisa"]


def test_obtener_producto(client, cabecera, producto):
    r = client.get(f"/productos/{producto['id']}", headers=cabecera("COCINA"))
    assert r.status_code == 200
    assert r.json()["id"] == producto["id"]


def test_obtener_inexistente_es_404(client, admin):
    assert client.get("/productos/999", headers=admin).status_code == 404


def test_actualizar_producto(client, admin, producto):
    r = client.put(
        f"/productos/{producto['id']}",
        json={"precio": 35000.5, "descripcion": "Con chicharrón"},
        headers=admin,
    )
    assert r.status_code == 200
    assert r.json()["precio"] == 35000.5
    assert r.json()["descripcion"] == "Con chicharrón"
    assert r.json()["nombre"] == "Bandeja paisa"


def test_actualizar_con_categoria_inexistente(client, admin, producto):
    r = client.put(f"/productos/{producto['id']}", json={"categoria_id": 999}, headers=admin)
    assert r.status_code == 404


def test_actualizar_inexistente_es_404(client, admin):
    assert client.put("/productos/999", json={"nombre": "X"}, headers=admin).status_code == 404


def test_desactivar_inexistente_es_404(client, admin):
    assert client.delete("/productos/999", headers=admin).status_code == 404


def test_mesero_no_actualiza_ni_borra(client, cabecera, producto):
    mesero = cabecera("MESERO")
    assert client.put(f"/productos/{producto['id']}", json={"nombre": "X"}, headers=mesero).status_code == 403
    assert client.delete(f"/productos/{producto['id']}", headers=mesero).status_code == 403


# ---------- inventario ----------
def _mover(client, producto_id, tipo, cantidad, headers, motivo=None):
    return client.post(
        f"/productos/{producto_id}/movimientos",
        json={"tipo": tipo, "cantidad": cantidad, "motivo": motivo},
        headers=headers,
    )


def test_el_stock_se_calcula_con_movimientos(client, admin, producto):
    pid = producto["id"]
    assert _mover(client, pid, "ENTRADA", 20, admin, "Compra").json()["stock_resultante"] == 20
    assert _mover(client, pid, "SALIDA", 5, admin).json()["stock_resultante"] == 15
    assert _mover(client, pid, "AJUSTE", -2, admin, "Merma").json()["stock_resultante"] == 13
    assert _mover(client, pid, "AJUSTE", 1, admin).json()["stock_resultante"] == 14

    assert client.get(f"/productos/{pid}", headers=admin).json()["stock"] == 14
    lista = client.get("/productos", headers=admin).json()
    assert lista[0]["stock"] == 14

    historial = client.get(f"/productos/{pid}/movimientos", headers=admin).json()
    assert [m["stock_resultante"] for m in historial] == [20, 15, 13, 14]


def test_no_se_permite_stock_negativo(client, admin, producto):
    pid = producto["id"]
    _mover(client, pid, "ENTRADA", 3, admin)
    r = _mover(client, pid, "SALIDA", 4, admin)
    assert r.status_code == 409
    assert client.get(f"/productos/{pid}", headers=admin).json()["stock"] == 3


def test_ajuste_que_deja_stock_negativo_es_409(client, admin, producto):
    assert _mover(client, producto["id"], "AJUSTE", -1, admin).status_code == 409


def test_cantidades_invalidas(client, admin, producto):
    pid = producto["id"]
    assert _mover(client, pid, "ENTRADA", 0, admin).status_code == 422
    assert _mover(client, pid, "SALIDA", -3, admin).status_code == 422
    assert _mover(client, pid, "AJUSTE", 0, admin).status_code == 422
    assert _mover(client, pid, "OTRO", 1, admin).status_code == 422


def test_movimiento_de_producto_inexistente(client, admin):
    assert _mover(client, 999, "ENTRADA", 1, admin).status_code == 404


def test_otros_roles_no_mueven_inventario(client, cabecera, producto):
    for rol in ("MESERO", "COCINA", "CAJERO"):
        assert _mover(client, producto["id"], "ENTRADA", 1, cabecera(rol)).status_code == 403


def test_movimiento_sin_credenciales(client, producto):
    assert _mover(client, producto["id"], "ENTRADA", 1, {}).status_code == 401


def test_el_servicio_de_pedidos_puede_registrar_salidas(client, admin, producto):
    pid = producto["id"]
    _mover(client, pid, "ENTRADA", 10, admin)
    r = _mover(client, pid, "SALIDA", 2, SERVICIO, "Pedido #1")
    assert r.status_code == 201
    assert r.json()["registrado_por"] == "servicio"
    assert r.json()["stock_resultante"] == 8


def test_token_de_servicio_incorrecto(client, producto):
    r = _mover(client, producto["id"], "ENTRADA", 1, {"X-Service-Token": "incorrecto"})
    assert r.status_code == 401


def test_token_de_servicio_no_configurado(client, producto, monkeypatch):
    monkeypatch.delenv("SERVICE_TOKEN")
    r = _mover(client, producto["id"], "ENTRADA", 1, {"X-Service-Token": ""})
    assert r.status_code == 401


def test_solo_admin_ve_el_historial(client, cabecera, producto):
    r = client.get(f"/productos/{producto['id']}/movimientos", headers=cabecera("MESERO"))
    assert r.status_code == 403


def test_historial_de_inexistente_es_404(client, admin):
    assert client.get("/productos/999/movimientos", headers=admin).status_code == 404


# ---------- arranque ----------
def test_crear_tablas_reintenta(monkeypatch):
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


def test_el_arranque_de_la_app_crea_tablas():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as cliente:
        assert cliente.get("/productos/health").status_code == 200
