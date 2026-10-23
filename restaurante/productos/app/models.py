"""Entidades del servicio de productos: Categoría, Producto y MovimientoInventario."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

ENTRADA = "ENTRADA"
SALIDA = "SALIDA"
AJUSTE = "AJUSTE"


def _ahora() -> datetime:
    return datetime.now(UTC)


class Categoria(Base):
    __tablename__ = "categorias"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80), unique=True)


class Producto(Base):
    __tablename__ = "productos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), index=True)
    descripcion: Mapped[str | None] = mapped_column(String(300), default=None)
    precio: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    categoria_id: Mapped[int] = mapped_column(ForeignKey("categorias.id"))


class MovimientoInventario(Base):
    """El stock no se guarda: se calcula sumando los movimientos.

    ENTRADA suma, SALIDA resta y AJUSTE suma su cantidad con signo.
    """

    __tablename__ = "movimientos_inventario"

    id: Mapped[int] = mapped_column(primary_key=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(10))
    cantidad: Mapped[int] = mapped_column()
    motivo: Mapped[str | None] = mapped_column(String(200), default=None)
    registrado_por: Mapped[str] = mapped_column(String(40))
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)
