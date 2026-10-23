import logging

import pytest
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app import bootstrap, eventos, routes
from app.database import SessionLocal
from app.models import Notificacion


# ---------- health y autenticación ----------
def test_health_ok(client):
    r = client.get("/pedidos/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_503_si_la_base_falla(client, monkeypatch):
    class MotorRoto:
        def connect(self):
            raise SQLAlchemyError("sin conexión")

    monkeypatch.setattr(routes, "engine", MotorRoto())
    assert client.get("/pedidos/health").status_code == 503


def test_sin_token_es_401(client):
    assert client.get("/pedidos").status_code == 401
    assert client.get("/pedidos/mesas").status_code == 401


def test_token_invalido_es_401(client):
    r = client.get("/pedidos", headers={"Authorization": "Bearer basura"})
    assert r.status_code == 401


# ---------- mesas ----------
def test_admin_crea_y_lista_mesas(client, admin, mesero, mesa):
    assert mesa["estado"] == "LIBRE"
    r = client.get("/pedidos/mesas", headers=mesero)
    assert [m["numero"] for m in r.json()] == [5]


def test_mesa_repetida_es_409(client, admin, mesa):
    r = client.post("/pedidos/mesas", json={"numero": 5}, headers=admin)
    assert r.status_code == 409


def test_mesero_no_crea_mesas(client, mesero):
    assert client.post("/pedidos/mesas", json={"numero": 9}, headers=mesero).status_code == 403


# ---------- crear pedido ----------
def test_crear_pedido_guarda_precios_del_momento_y_descuenta_stock(client, productos, pedido):
    assert pedido["estado"] == "PENDIENTE"
    assert pedido["mesero_id"] == 10
    assert pedido["total"] == 70500.5
    assert pedido["pago"] is None
    bandeja = pedido["detalles"][0]
    assert bandeja["nombre_producto"] == "Bandeja paisa"
    assert bandeja["precio_unitario"] == 32000
    assert bandeja["nota"] == "sin cebolla"
    # El inventario se descontó en el servicio de productos.
    assert productos.catalogo[1]["stock"] == 8
    assert productos.catalogo[2]["stock"] == 4
    assert (1, "SALIDA", 2, f"Pedido #{pedido['id']}") in productos.movimientos


def test_el_precio_guardado_no_cambia_si_el_menu_cambia(client, productos, pedido, mesero):
    productos.catalogo[1]["precio"] = 99999.0
    r = client.get(f"/pedidos/{pedido['id']}", headers=mesero)
    assert r.json()["detalles"][0]["precio_unitario"] == 32000
    assert r.json()["total"] == 70500.5


def test_la_mesa_queda_ocupada(client, mesero, pedido):
    mesas = client.get("/pedidos/mesas", headers=mesero).json()
    assert mesas[0]["estado"] == "OCUPADA"


def test_lineas_repetidas_se_suman_para_validar_stock(client, mesero, mesa, productos):
    r = client.post(
        "/pedidos",
        json={
            "mesa_id": mesa["id"],
            "items": [{"producto_id": 2, "cantidad": 3}, {"producto_id": 2, "cantidad": 3}],
        },
        headers=mesero,
    )
    assert r.status_code == 409
    assert productos.catalogo[2]["stock"] == 5


def test_mesa_inexistente(client, mesero):
    r = client.post(
        "/pedidos",
        json={"mesa_id": 999, "items": [{"producto_id": 1, "cantidad": 1}]},
        headers=mesero,
    )
    assert r.status_code == 404


@pytest.mark.parametrize(
    ("producto_id", "codigo"),
    [(99, 404), (3, 409), (4, 409)],
    ids=["no-existe", "sin-stock", "retirado-del-menu"],
)
def test_productos_no_validos(client, mesero, mesa, producto_id, codigo):
    r = client.post(
        "/pedidos",
        json={"mesa_id": mesa["id"], "items": [{"producto_id": producto_id, "cantidad": 1}]},
        headers=mesero,
    )
    assert r.status_code == codigo


def test_pedido_vacio_o_con_cantidad_invalida(client, mesero, mesa):
    assert client.post("/pedidos", json={"mesa_id": mesa["id"], "items": []}, headers=mesero).status_code == 422
    r = client.post(
        "/pedidos",
        json={"mesa_id": mesa["id"], "items": [{"producto_id": 1, "cantidad": 0}]},
        headers=mesero,
    )
    assert r.status_code == 422


def test_servicio_de_productos_caido_es_503(client, mesero, mesa, productos):
    productos.caido = True
    r = client.post(
        "/pedidos",
        json={"mesa_id": mesa["id"], "items": [{"producto_id": 1, "cantidad": 1}]},
        headers=mesero,
    )
    assert r.status_code == 503


def test_si_falla_el_descuento_se_deshace_todo(client, mesero, mesa, productos):
    productos.fallar_salida_del_producto = 2  # la salida del jugo falla tras la de la bandeja
    r = client.post(
        "/pedidos",
        json={
            "mesa_id": mesa["id"],
            "items": [{"producto_id": 1, "cantidad": 2}, {"producto_id": 2, "cantidad": 1}],
        },
        headers=mesero,
    )
    assert r.status_code == 409
    assert productos.catalogo[1]["stock"] == 10  # compensado
    assert client.get("/pedidos", headers=mesero).json() == []
    assert client.get("/pedidos/mesas", headers=mesero).json()[0]["estado"] == "LIBRE"


def test_si_productos_cae_durante_el_descuento_es_503(client, mesero, mesa, productos):
    class SeCaeAlDescontar:
        def __init__(self, base):
            self.base = base

        def obtener_producto(self, producto_id, authorization):
            return self.base.obtener_producto(producto_id, authorization)

        def registrar_movimiento(self, *args):
            self.base.caido = True
            return self.base.registrar_movimiento(*args)

    from app.clients import get_productos_client
    from app.main import app

    app.dependency_overrides[get_productos_client] = lambda: SeCaeAlDescontar(productos)
    r = client.post(
        "/pedidos",
        json={"mesa_id": mesa["id"], "items": [{"producto_id": 1, "cantidad": 1}]},
        headers=mesero,
    )
    assert r.status_code == 503
    assert client.get("/pedidos", headers=mesero).json() == []


def test_cocina_y_cajero_no_crean_pedidos(client, cocina, cajero, mesa):
    cuerpo = {"mesa_id": mesa["id"], "items": [{"producto_id": 1, "cantidad": 1}]}
    assert client.post("/pedidos", json=cuerpo, headers=cocina).status_code == 403
    assert client.post("/pedidos", json=cuerpo, headers=cajero).status_code == 403


# ---------- consultar pedidos ----------
def test_un_mesero_solo_ve_sus_pedidos(client, cabecera, pedido):
    otro = cabecera("MESERO", usuario_id=11)
    assert client.get("/pedidos", headers=otro).json() == []
    assert client.get(f"/pedidos/{pedido['id']}", headers=otro).status_code == 403
    suyo = cabecera("MESERO", usuario_id=10)
    assert len(client.get("/pedidos", headers=suyo).json()) == 1
    assert client.get(f"/pedidos/{pedido['id']}", headers=suyo).status_code == 200


def test_cocina_ve_el_tablero_y_filtra_por_estado(client, cocina, pedido):
    todos = client.get("/pedidos", headers=cocina).json()
    assert len(todos) == 1
    r = client.get("/pedidos?estado=PENDIENTE&estado=EN_PREPARACION", headers=cocina)
    assert len(r.json()) == 1
    assert client.get("/pedidos?estado=LISTO", headers=cocina).json() == []


def test_estado_de_filtro_invalido_es_422(client, cocina):
    assert client.get("/pedidos?estado=INVENTADO", headers=cocina).status_code == 422


def test_pedido_inexistente_es_404(client, admin):
    assert client.get("/pedidos/999", headers=admin).status_code == 404


# ---------- estados de preparación ----------
def test_ciclo_completo_de_estados(client, pedido, cocina, mesero):
    pid = pedido["id"]
    r = client.patch(f"/pedidos/{pid}/estado", json={"estado": "EN_PREPARACION"}, headers=cocina)
    assert r.json()["estado"] == "EN_PREPARACION"
    r = client.patch(f"/pedidos/{pid}/estado", json={"estado": "LISTO"}, headers=cocina)
    assert r.json()["estado"] == "LISTO"
    r = client.patch(f"/pedidos/{pid}/estado", json={"estado": "ENTREGADO"}, headers=mesero)
    assert r.json()["estado"] == "ENTREGADO"


def test_no_se_puede_saltar_ni_retroceder(client, pedido, cocina, pedido_listo):
    pid = pedido["id"]
    for nuevo in ("PENDIENTE", "EN_PREPARACION", "LISTO"):
        r = client.patch(f"/pedidos/{pid}/estado", json={"estado": nuevo}, headers=cocina)
        assert r.status_code == 409


def test_no_se_salta_de_pendiente_a_listo(client, pedido, cocina):
    r = client.patch(f"/pedidos/{pedido['id']}/estado", json={"estado": "LISTO"}, headers=cocina)
    assert r.status_code == 409


def test_cada_cambio_exige_su_rol(client, pedido, mesero, cajero, cocina):
    pid = pedido["id"]
    for cabecera in (mesero, cajero):
        r = client.patch(f"/pedidos/{pid}/estado", json={"estado": "EN_PREPARACION"}, headers=cabecera)
        assert r.status_code == 403
    client.patch(f"/pedidos/{pid}/estado", json={"estado": "EN_PREPARACION"}, headers=cocina)
    client.patch(f"/pedidos/{pid}/estado", json={"estado": "LISTO"}, headers=cocina)
    # Cocina no entrega.
    r = client.patch(f"/pedidos/{pid}/estado", json={"estado": "ENTREGADO"}, headers=cocina)
    assert r.status_code == 403


def test_otro_mesero_no_entrega_pedido_ajeno(client, cabecera, pedido_listo):
    otro = cabecera("MESERO", usuario_id=11)
    r = client.patch(f"/pedidos/{pedido_listo['id']}/estado", json={"estado": "ENTREGADO"}, headers=otro)
    assert r.status_code == 403


def test_estado_inexistente_en_la_ruta(client, cocina):
    r = client.patch("/pedidos/999/estado", json={"estado": "LISTO"}, headers=cocina)
    assert r.status_code == 404


# ---------- evento "pedido listo" → aviso al cajero ----------
def test_pedido_listo_notifica_al_cajero(client, cajero, pedido_listo):
    r = client.get("/pedidos/notificaciones", headers=cajero)
    assert r.status_code == 200
    avisos = r.json()
    assert len(avisos) == 1
    assert avisos[0]["pedido_id"] == pedido_listo["id"]
    assert "mesa 5" in avisos[0]["mensaje"]
    assert avisos[0]["leida"] is False


def test_solo_un_aviso_por_pedido_listo(client, cajero, pedido, cocina):
    client.patch(f"/pedidos/{pedido['id']}/estado", json={"estado": "EN_PREPARACION"}, headers=cocina)
    assert client.get("/pedidos/notificaciones", headers=cajero).json() == []


def test_marcar_aviso_como_leido(client, cajero, pedido_listo):
    aviso = client.get("/pedidos/notificaciones", headers=cajero).json()[0]
    r = client.post(f"/pedidos/notificaciones/{aviso['id']}/leida", headers=cajero)
    assert r.json()["leida"] is True
    assert client.get("/pedidos/notificaciones?solo_no_leidas=true", headers=cajero).json() == []
    assert len(client.get("/pedidos/notificaciones", headers=cajero).json()) == 1


def test_marcar_aviso_inexistente(client, cajero):
    assert client.post("/pedidos/notificaciones/999/leida", headers=cajero).status_code == 404


def test_cocina_y_mesero_no_ven_avisos(client, cocina, mesero):
    assert client.get("/pedidos/notificaciones", headers=cocina).status_code == 403
    assert client.get("/pedidos/notificaciones", headers=mesero).status_code == 403


def test_un_suscriptor_con_error_no_tumba_la_operacion(client, pedido, cocina, monkeypatch, caplog):
    def roto(_db, _datos):
        raise RuntimeError("falla del suscriptor")

    monkeypatch.setitem(eventos._suscriptores, eventos.PEDIDO_LISTO, [roto])
    client.patch(f"/pedidos/{pedido['id']}/estado", json={"estado": "EN_PREPARACION"}, headers=cocina)
    with caplog.at_level(logging.ERROR):
        r = client.patch(f"/pedidos/{pedido['id']}/estado", json={"estado": "LISTO"}, headers=cocina)
    assert r.status_code == 200
    assert "Falló el manejador roto" in caplog.text
    with SessionLocal() as db:
        assert db.query(Notificacion).count() == 0


def test_suscribir_no_duplica_manejadores():
    cuenta_antes = len(eventos._suscriptores[eventos.PEDIDO_LISTO])
    eventos.registrar_suscriptores()
    eventos.registrar_suscriptores()
    assert len(eventos._suscriptores[eventos.PEDIDO_LISTO]) == cuenta_antes


# ---------- pagos ----------
def pagar(client, pedido_id, monto, cabecera, metodo="EFECTIVO"):
    return client.post(
        f"/pedidos/{pedido_id}/pago", json={"monto": monto, "metodo": metodo}, headers=cabecera
    )


def test_cajero_valida_el_pago_y_la_mesa_se_libera(client, cajero, mesero, pedido_listo):
    r = pagar(client, pedido_listo["id"], 70500.5, cajero, "TARJETA")
    assert r.status_code == 201
    cuerpo = r.json()
    assert cuerpo["monto"] == 70500.5
    assert cuerpo["metodo"] == "TARJETA"
    assert cuerpo["validado_por"] == 30
    assert client.get("/pedidos/mesas", headers=mesero).json()[0]["estado"] == "LIBRE"
    con_pago = client.get(f"/pedidos/{pedido_listo['id']}", headers=mesero).json()
    assert con_pago["pago"]["id"] == cuerpo["id"]


def test_no_se_cobra_un_pedido_que_no_esta_listo(client, cajero, pedido):
    assert pagar(client, pedido["id"], 70500.5, cajero).status_code == 409


def test_no_se_paga_dos_veces(client, cajero, pedido_listo):
    assert pagar(client, pedido_listo["id"], 70500.5, cajero).status_code == 201
    assert pagar(client, pedido_listo["id"], 70500.5, cajero).status_code == 409


def test_el_monto_debe_coincidir_con_el_total(client, cajero, pedido_listo):
    assert pagar(client, pedido_listo["id"], 1000, cajero).status_code == 422


def test_pago_con_datos_invalidos(client, cajero, pedido_listo):
    assert pagar(client, pedido_listo["id"], -5, cajero).status_code == 422
    assert pagar(client, pedido_listo["id"], 70500.5, cajero, "BITCOIN").status_code == 422


def test_pago_de_pedido_inexistente(client, cajero):
    assert pagar(client, 999, 10, cajero).status_code == 404


def test_solo_cajero_y_admin_cobran(client, mesero, cocina, admin, pedido_listo):
    assert pagar(client, pedido_listo["id"], 70500.5, mesero).status_code == 403
    assert pagar(client, pedido_listo["id"], 70500.5, cocina).status_code == 403
    assert pagar(client, pedido_listo["id"], 70500.5, admin).status_code == 201


def test_la_mesa_sigue_ocupada_si_quedan_pedidos_sin_pagar(client, cajero, mesero, mesa, pedido_listo):
    segundo = client.post(
        "/pedidos",
        json={"mesa_id": mesa["id"], "items": [{"producto_id": 2, "cantidad": 1}]},
        headers=mesero,
    )
    assert segundo.status_code == 201
    pagar(client, pedido_listo["id"], 70500.5, cajero)
    assert client.get("/pedidos/mesas", headers=mesero).json()[0]["estado"] == "OCUPADA"


# ---------- ventas ----------
def test_ventas_suma_los_pagos(client, admin, cajero, pedido_listo):
    vacio = client.get("/pedidos/ventas", headers=admin).json()
    assert vacio == {"total": 0, "pagos": 0}
    pagar(client, pedido_listo["id"], 70500.5, cajero)
    r = client.get("/pedidos/ventas", headers=admin).json()
    assert r == {"total": 70500.5, "pagos": 1}


def test_solo_admin_ve_ventas(client, cajero, mesero):
    assert client.get("/pedidos/ventas", headers=cajero).status_code == 403
    assert client.get("/pedidos/ventas", headers=mesero).status_code == 403


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


def test_el_arranque_de_la_app_crea_tablas(client):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as cliente:
        assert cliente.get("/pedidos/health").status_code == 200
