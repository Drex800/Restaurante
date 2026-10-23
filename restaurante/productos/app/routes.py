"""Endpoints del servicio de productos, categorías e inventario."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import case, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app.models import AJUSTE, SALIDA, Categoria, MovimientoInventario, Producto
from app.roles import ADMIN
from app.schemas import (
    CategoriaCrear,
    CategoriaSalida,
    MovimientoCrear,
    MovimientoSalida,
    ProductoActualizar,
    ProductoCrear,
    ProductoSalida,
)
from app.security import autorizar_movimiento, requiere_roles, usuario_actual

router = APIRouter(prefix="/productos", tags=["productos"])

DB = Annotated[Session, Depends(get_db)]
Autenticado = Annotated[dict, Depends(usuario_actual)]
Admin = Annotated[dict, Depends(requiere_roles(ADMIN))]
QuienMueve = Annotated[str, Depends(autorizar_movimiento)]


def _suma_stock():
    """Entradas y ajustes suman; las salidas restan."""
    return func.coalesce(
        func.sum(
            case(
                (MovimientoInventario.tipo == SALIDA, -MovimientoInventario.cantidad),
                else_=MovimientoInventario.cantidad,
            )
        ),
        0,
    )


def calcular_stock(db: Session, producto_id: int) -> int:
    consulta = select(_suma_stock()).where(MovimientoInventario.producto_id == producto_id)
    return int(db.scalar(consulta))


def _salida(producto: Producto, stock: int) -> ProductoSalida:
    return ProductoSalida(
        id=producto.id,
        nombre=producto.nombre,
        descripcion=producto.descripcion,
        precio=producto.precio,
        activo=producto.activo,
        categoria_id=producto.categoria_id,
        stock=stock,
    )


def _buscar(db: Session, producto_id: int) -> Producto:
    producto = db.get(Producto, producto_id)
    if producto is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Producto no encontrado")
    return producto


def _exigir_categoria(db: Session, categoria_id: int) -> None:
    if db.get(Categoria, categoria_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La categoría no existe")


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


# ---------- categorías ----------
@router.get("/categorias", response_model=list[CategoriaSalida])
def listar_categorias(_: Autenticado, db: DB) -> list[Categoria]:
    return list(db.scalars(select(Categoria).order_by(Categoria.nombre)))


@router.post("/categorias", response_model=CategoriaSalida, status_code=status.HTTP_201_CREATED)
def crear_categoria(datos: CategoriaCrear, _: Admin, db: DB) -> Categoria:
    if db.scalar(select(Categoria).where(Categoria.nombre == datos.nombre)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "La categoría ya existe")
    categoria = Categoria(nombre=datos.nombre)
    db.add(categoria)
    db.commit()
    return categoria


# ---------- productos ----------
@router.get("", response_model=list[ProductoSalida])
def listar(
    _: Autenticado,
    db: DB,
    categoria_id: Annotated[int | None, Query()] = None,
) -> list[ProductoSalida]:
    consulta = select(Producto).where(Producto.activo.is_(True)).order_by(Producto.nombre)
    if categoria_id is not None:
        consulta = consulta.where(Producto.categoria_id == categoria_id)
    stocks = dict(
        db.execute(
            select(MovimientoInventario.producto_id, _suma_stock()).group_by(
                MovimientoInventario.producto_id
            )
        ).all()
    )
    return [_salida(p, int(stocks.get(p.id, 0))) for p in db.scalars(consulta)]


@router.post("", response_model=ProductoSalida, status_code=status.HTTP_201_CREATED)
def crear(datos: ProductoCrear, _: Admin, db: DB) -> ProductoSalida:
    _exigir_categoria(db, datos.categoria_id)
    producto = Producto(**datos.model_dump())
    db.add(producto)
    db.commit()
    return _salida(producto, 0)


@router.get("/{producto_id}", response_model=ProductoSalida)
def obtener(producto_id: int, _: Autenticado, db: DB) -> ProductoSalida:
    producto = _buscar(db, producto_id)
    return _salida(producto, calcular_stock(db, producto_id))


@router.put("/{producto_id}", response_model=ProductoSalida)
def actualizar(
    producto_id: int, datos: ProductoActualizar, _: Admin, db: DB
) -> ProductoSalida:
    producto = _buscar(db, producto_id)
    cambios = datos.model_dump(exclude_unset=True)
    if "categoria_id" in cambios:
        _exigir_categoria(db, cambios["categoria_id"])
    for campo, valor in cambios.items():
        if valor is None and campo != "descripcion":
            continue
        setattr(producto, campo, valor)
    db.commit()
    return _salida(producto, calcular_stock(db, producto_id))


@router.delete("/{producto_id}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar(producto_id: int, _: Admin, db: DB) -> Response:
    producto = _buscar(db, producto_id)
    producto.activo = False
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- inventario ----------
@router.post(
    "/{producto_id}/movimientos",
    response_model=MovimientoSalida,
    status_code=status.HTTP_201_CREATED,
)
def registrar_movimiento(
    producto_id: int, datos: MovimientoCrear, quien: QuienMueve, db: DB
) -> MovimientoSalida:
    _buscar(db, producto_id)
    if datos.tipo == AJUSTE:
        if datos.cantidad == 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El ajuste no puede ser 0")
    elif datos.cantidad <= 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "La cantidad debe ser mayor que 0"
        )

    stock = calcular_stock(db, producto_id)
    efecto = -datos.cantidad if datos.tipo == SALIDA else datos.cantidad
    if stock + efecto < 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Stock insuficiente: hay {stock} y se piden {-efecto}"
        )

    movimiento = MovimientoInventario(
        producto_id=producto_id,
        tipo=datos.tipo,
        cantidad=datos.cantidad,
        motivo=datos.motivo,
        registrado_por=quien,
    )
    db.add(movimiento)
    db.commit()
    return MovimientoSalida(
        id=movimiento.id,
        producto_id=producto_id,
        tipo=movimiento.tipo,
        cantidad=movimiento.cantidad,
        motivo=movimiento.motivo,
        registrado_por=movimiento.registrado_por,
        creado_en=movimiento.creado_en,
        stock_resultante=stock + efecto,
    )


@router.get("/{producto_id}/movimientos", response_model=list[MovimientoSalida])
def listar_movimientos(producto_id: int, _: Admin, db: DB) -> list[MovimientoSalida]:
    _buscar(db, producto_id)
    movimientos = db.scalars(
        select(MovimientoInventario)
        .where(MovimientoInventario.producto_id == producto_id)
        .order_by(MovimientoInventario.id)
    ).all()
    corrido = 0
    salida = []
    for m in movimientos:
        corrido += -m.cantidad if m.tipo == SALIDA else m.cantidad
        salida.append(
            MovimientoSalida(
                id=m.id,
                producto_id=m.producto_id,
                tipo=m.tipo,
                cantidad=m.cantidad,
                motivo=m.motivo,
                registrado_por=m.registrado_por,
                creado_en=m.creado_en,
                stock_resultante=corrido,
            )
        )
    return salida
