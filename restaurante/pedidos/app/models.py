"""Entidades del servicio de pedidos: Mesa, Pedido, DetallePedido y Pago.

También guarda las notificaciones al cajero, que son el resultado del evento
"pedido listo".
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Estados del pedido: Pendiente → En preparación → Listo → Entregado
PENDIENTE = "PENDIENTE"
EN_PREPARACION = "EN_PREPARACION"
LISTO = "LISTO"
ENTREGADO = "ENTREGADO"

LIBRE = "LIBRE"
OCUPADA = "OCUPADA"


def _ahora() -> datetime:
    return datetime.now(UTC)


class Mesa(Base):
    __tablename__ = "mesas"

    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[int] = mapped_column(unique=True)
    capacidad: Mapped[int] = mapped_column(default=4)
    estado: Mapped[str] = mapped_column(String(10), default=LIBRE)


class Pedido(Base):
    __tablename__ = "pedidos"

    id: Mapped[int] = mapped_column(primary_key=True)
    mesa_id: Mapped[int] = mapped_column(ForeignKey("mesas.id"), index=True)
    # Id del usuario en el servicio de usuarios (referencia lógica, sin clave foránea).
    mesero_id: Mapped[int] = mapped_column()
    estado: Mapped[str] = mapped_column(String(20), default=PENDIENTE, index=True)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora, onupdate=_ahora)

    detalles: Mapped[list["DetallePedido"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="DetallePedido.id"
    )


class DetallePedido(Base):
    """Guarda el nombre y el precio del momento: el menú puede cambiar después."""

    __tablename__ = "detalles_pedido"

    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id"), index=True)
    # Id del producto en el servicio de productos (referencia lógica, sin clave foránea).
    producto_id: Mapped[int] = mapped_column()
    nombre_producto: Mapped[str] = mapped_column(String(120))
    cantidad: Mapped[int] = mapped_column()
    precio_unitario: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    nota: Mapped[str | None] = mapped_column(String(200), default=None)


class Pago(Base):
    __tablename__ = "pagos"

    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id"), unique=True)
    monto: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    metodo: Mapped[str] = mapped_column(String(20))
    validado_por: Mapped[int] = mapped_column()
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)


class Notificacion(Base):
    __tablename__ = "notificaciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id"), index=True)
    mensaje: Mapped[str] = mapped_column(String(200))
    leida: Mapped[bool] = mapped_column(Boolean, default=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)
