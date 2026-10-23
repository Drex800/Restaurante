"""Endpoints del servicio de pedidos: mesas, pedidos, pagos y avisos al cajero."""

import logging
from collections import defaultdict
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.clients import (
    ProductosClient,
    ProductosNoDisponible,
    StockInsuficiente,
    get_productos_client,
)
from app.database import engine, get_db
from app.eventos import (
    PEDIDO_CREADO,
    PEDIDO_ESTADO_CAMBIADO,
    PEDIDO_LISTO,
    publicar,
)
from app.models import (
    EN_PREPARACION,
    ENTREGADO,
    LIBRE,
    LISTO,
    OCUPADA,
    PENDIENTE,
    DetallePedido,
    Mesa,
    Notificacion,
    Pago,
    Pedido,
)
from app.roles import ADMIN, CAJERO, COCINA, MESERO
from app.schemas import (
    CambioEstado,
    DetalleSalida,
    EstadoPedido,
    MesaCrear,
    MesaSalida,
    NotificacionSalida,
    PagoCrear,
    PagoSalida,
    PedidoCrear,
    PedidoSalida,
    VentasSalida,
)
from app.security import requiere_roles, usuario_actual

logger = logging.getLogger("pedidos")

router = APIRouter(prefix="/pedidos", tags=["pedidos"])

DB = Annotated[Session, Depends(get_db)]
Autenticado = Annotated[dict, Depends(usuario_actual)]
Admin = Annotated[dict, Depends(requiere_roles(ADMIN))]
Mesero = Annotated[dict, Depends(requiere_roles(MESERO, ADMIN))]
Cajero = Annotated[dict, Depends(requiere_roles(CAJERO, ADMIN))]
Productos = Annotated[ProductosClient, Depends(get_productos_client)]
Autorizacion = Annotated[str, Header()]

# (estado actual, estado nuevo) → roles que pueden hacer el cambio
TRANSICIONES = {
    (PENDIENTE, EN_PREPARACION): {COCINA, ADMIN},
    (EN_PREPARACION, LISTO): {COCINA, ADMIN},
    (LISTO, ENTREGADO): {MESERO, ADMIN},
}


# ---------- utilidades ----------
def _salidas(db: Session, pedidos: list[Pedido]) -> list[PedidoSalida]:
    ids = [p.id for p in pedidos]
    pagos = {}
    if ids:
        pagos = {pg.pedido_id: pg for pg in db.scalars(select(Pago).where(Pago.pedido_id.in_(ids)))}
    resultado = []
    for p in pedidos:
        pago = pagos.get(p.id)
        resultado.append(
            PedidoSalida(
                id=p.id,
                mesa_id=p.mesa_id,
                mesero_id=p.mesero_id,
                estado=p.estado,
                total=p.total,
                creado_en=p.creado_en,
                actualizado_en=p.actualizado_en,
                detalles=[
                    DetalleSalida.model_validate(d, from_attributes=True) for d in p.detalles
                ],
                pago=PagoSalida.model_validate(pago, from_attributes=True) if pago else None,
            )
        )
    return resultado


def _buscar(db: Session, pedido_id: int) -> Pedido:
    pedido = db.get(Pedido, pedido_id)
    if pedido is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pedido no encontrado")
    return pedido


def _exigir_visible(actual: dict, pedido: Pedido) -> None:
    """Un mesero solo ve sus propios pedidos."""
    if actual["rol"] == MESERO and pedido.mesero_id != int(actual["sub"]):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ese pedido no es suyo")


def _compensar(productos: ProductosClient, hechas: list[tuple[int, int]], pedido_id: int) -> None:
    """Devuelve al inventario las salidas ya registradas si el pedido no se pudo completar."""
    for producto_id, cantidad in hechas:
        try:
            productos.registrar_movimiento(
                producto_id, "ENTRADA", cantidad, f"Compensación de pedido fallido #{pedido_id}"
            )
        except (StockInsuficiente, ProductosNoDisponible):
            logger.error(
                "No se pudo compensar el producto %s del pedido %s", producto_id, pedido_id
            )


@router.get("/health")
def health() -> dict:
    try:
        with engine.connect() as conexion:
            conexion.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Base de datos no disponible"
        ) from exc
    return {"status": "ok"}


# ---------- mesas ----------
@router.get("/mesas", response_model=list[MesaSalida])
def listar_mesas(_: Autenticado, db: DB) -> list[Mesa]:
    return list(db.scalars(select(Mesa).order_by(Mesa.numero)))


@router.post("/mesas", response_model=MesaSalida, status_code=status.HTTP_201_CREATED)
def crear_mesa(datos: MesaCrear, _: Admin, db: DB) -> Mesa:
    if db.scalar(select(Mesa).where(Mesa.numero == datos.numero)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe una mesa con ese número")
    mesa = Mesa(numero=datos.numero, capacidad=datos.capacidad)
    db.add(mesa)
    db.commit()
    return mesa


# ---------- avisos al cajero ----------
@router.get("/notificaciones", response_model=list[NotificacionSalida])
def listar_notificaciones(
    _: Cajero,
    db: DB,
    solo_no_leidas: Annotated[bool, Query()] = False,
) -> list[Notificacion]:
    consulta = select(Notificacion).order_by(Notificacion.id)
    if solo_no_leidas:
        consulta = consulta.where(Notificacion.leida.is_(False))
    return list(db.scalars(consulta))


@router.post("/notificaciones/{notificacion_id}/leida", response_model=NotificacionSalida)
def marcar_leida(notificacion_id: int, _: Cajero, db: DB) -> Notificacion:
    notificacion = db.get(Notificacion, notificacion_id)
    if notificacion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notificación no encontrada")
    notificacion.leida = True
    db.commit()
    return notificacion


# ---------- ventas ----------
@router.get("/ventas", response_model=VentasSalida)
def ventas(_: Admin, db: DB) -> VentasSalida:
    total, cantidad = db.execute(
        select(func.coalesce(func.sum(Pago.monto), 0), func.count(Pago.id))
    ).one()
    return VentasSalida(total=Decimal(str(total)), pagos=cantidad)


# ---------- pedidos ----------
@router.post("", response_model=PedidoSalida, status_code=status.HTTP_201_CREATED)
def crear_pedido(
    datos: PedidoCrear,
    actual: Mesero,
    authorization: Autorizacion,
    db: DB,
    productos: Productos,
) -> PedidoSalida:
    mesa = db.get(Mesa, datos.mesa_id)
    if mesa is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La mesa no existe")

    cantidades: dict[int, int] = defaultdict(int)
    for item in datos.items:
        cantidades[item.producto_id] += item.cantidad

    # 1) Validar cada producto (existencia, disponibilidad y stock) con el servicio de productos.
    catalogo: dict[int, dict] = {}
    try:
        for producto_id, cantidad in cantidades.items():
            producto = productos.obtener_producto(producto_id, authorization)
            if producto is None:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND, f"El producto {producto_id} no existe"
                )
            if not producto["activo"]:
                raise HTTPException(
                    status.HTTP_409_CONFLICT, f"{producto['nombre']} no está disponible"
                )
            if producto["stock"] < cantidad:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"Stock insuficiente de {producto['nombre']}: hay {producto['stock']}",
                )
            catalogo[producto_id] = producto
    except ProductosNoDisponible as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "El servicio de productos no está disponible"
        ) from exc

    # 2) Guardar el pedido con el precio del momento.
    total = Decimal("0.00")
    detalles = []
    for item in datos.items:
        producto = catalogo[item.producto_id]
        precio = Decimal(str(producto["precio"]))
        total += precio * item.cantidad
        detalles.append(
            DetallePedido(
                producto_id=item.producto_id,
                nombre_producto=producto["nombre"],
                cantidad=item.cantidad,
                precio_unitario=precio,
                nota=item.nota,
            )
        )
    pedido = Pedido(
        mesa_id=mesa.id,
        mesero_id=int(actual["sub"]),
        total=total.quantize(Decimal("0.01")),
        detalles=detalles,
    )
    db.add(pedido)
    db.flush()

    # 3) Descontar del inventario; si algo falla, se deshace todo.
    hechas: list[tuple[int, int]] = []
    try:
        for producto_id, cantidad in cantidades.items():
            productos.registrar_movimiento(producto_id, "SALIDA", cantidad, f"Pedido #{pedido.id}")
            hechas.append((producto_id, cantidad))
    except (StockInsuficiente, ProductosNoDisponible) as exc:
        _compensar(productos, hechas, pedido.id)
        db.rollback()
        if isinstance(exc, StockInsuficiente):
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "El servicio de productos no está disponible"
        ) from exc

    mesa.estado = OCUPADA
    db.commit()
    publicar(
        PEDIDO_CREADO,
        db,
        {"pedido_id": pedido.id, "estado": PENDIENTE, "usuario_id": int(actual["sub"])},
    )
    return _salidas(db, [pedido])[0]


@router.get("", response_model=list[PedidoSalida])
def listar(
    actual: Autenticado,
    db: DB,
    estado: Annotated[list[EstadoPedido] | None, Query()] = None,
) -> list[PedidoSalida]:
    """Tablero de cocina: pedidos más antiguos primero. Un mesero solo ve los suyos."""
    consulta = select(Pedido).order_by(Pedido.creado_en, Pedido.id)
    if estado:
        consulta = consulta.where(Pedido.estado.in_(estado))
    if actual["rol"] == MESERO:
        consulta = consulta.where(Pedido.mesero_id == int(actual["sub"]))
    return _salidas(db, list(db.scalars(consulta)))


@router.get("/{pedido_id}", response_model=PedidoSalida)
def obtener(pedido_id: int, actual: Autenticado, db: DB) -> PedidoSalida:
    pedido = _buscar(db, pedido_id)
    _exigir_visible(actual, pedido)
    return _salidas(db, [pedido])[0]


@router.patch("/{pedido_id}/estado", response_model=PedidoSalida)
def cambiar_estado(
    pedido_id: int, datos: CambioEstado, actual: Autenticado, db: DB
) -> PedidoSalida:
    pedido = _buscar(db, pedido_id)
    permitidos = TRANSICIONES.get((pedido.estado, datos.estado))
    if permitidos is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"No se puede pasar de {pedido.estado} a {datos.estado}"
        )
    if actual["rol"] not in permitidos:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Su rol no puede hacer este cambio")
    _exigir_visible(actual, pedido)

    pedido.estado = datos.estado
    db.commit()

    mesa = db.get(Mesa, pedido.mesa_id)
    evento = {
        "pedido_id": pedido.id,
        "estado": pedido.estado,
        "usuario_id": int(actual["sub"]),
        "mesa_numero": mesa.numero,
    }
    publicar(PEDIDO_ESTADO_CAMBIADO, db, evento)
    if pedido.estado == LISTO:
        publicar(PEDIDO_LISTO, db, evento)
    return _salidas(db, [pedido])[0]


@router.post("/{pedido_id}/pago", response_model=PagoSalida, status_code=status.HTTP_201_CREATED)
def pagar(pedido_id: int, datos: PagoCrear, actual: Cajero, db: DB) -> Pago:
    pedido = _buscar(db, pedido_id)
    if pedido.estado not in (LISTO, ENTREGADO):
        raise HTTPException(status.HTTP_409_CONFLICT, "El pedido aún no está listo para cobrar")
    if db.scalar(select(Pago).where(Pago.pedido_id == pedido_id)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "El pedido ya fue pagado")
    if datos.monto != pedido.total:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"El monto debe ser igual al total: {pedido.total}",
        )

    pago = Pago(
        pedido_id=pedido_id,
        monto=datos.monto,
        metodo=datos.metodo,
        validado_por=int(actual["sub"]),
    )
    db.add(pago)
    db.flush()

    # La mesa queda libre cuando ya no tiene pedidos sin pagar.
    sin_pagar = db.scalar(
        select(func.count(Pedido.id))
        .select_from(Pedido)
        .outerjoin(Pago, Pago.pedido_id == Pedido.id)
        .where(Pedido.mesa_id == pedido.mesa_id, Pago.id.is_(None))
    )
    if sin_pagar == 0:
        db.get(Mesa, pedido.mesa_id).estado = LIBRE
    db.commit()
    return pago
