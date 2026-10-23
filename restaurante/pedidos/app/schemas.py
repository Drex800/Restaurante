"""Esquemas de entrada y salida de la API de pedidos."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

# El dinero se maneja como Decimal y se entrega como número JSON.
Dinero = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]

EstadoPedido = Literal["PENDIENTE", "EN_PREPARACION", "LISTO", "ENTREGADO"]
MetodoPago = Literal["EFECTIVO", "TARJETA", "TRANSFERENCIA"]


class MesaCrear(BaseModel):
    numero: int = Field(gt=0)
    capacidad: int = Field(default=4, gt=0, le=50)


class MesaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    numero: int
    capacidad: int
    estado: str


class ItemEntrada(BaseModel):
    producto_id: int
    cantidad: int = Field(gt=0, le=100)
    nota: str | None = Field(default=None, max_length=200)


class PedidoCrear(BaseModel):
    mesa_id: int
    items: list[ItemEntrada] = Field(min_length=1, max_length=50)


class CambioEstado(BaseModel):
    estado: EstadoPedido


class DetalleSalida(BaseModel):
    producto_id: int
    nombre_producto: str
    cantidad: int
    precio_unitario: Dinero
    nota: str | None


class PagoCrear(BaseModel):
    monto: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    metodo: MetodoPago


class PagoSalida(BaseModel):
    id: int
    pedido_id: int
    monto: Dinero
    metodo: str
    validado_por: int
    creado_en: datetime


class PedidoSalida(BaseModel):
    id: int
    mesa_id: int
    mesero_id: int
    estado: str
    total: Dinero
    creado_en: datetime
    actualizado_en: datetime
    detalles: list[DetalleSalida]
    pago: PagoSalida | None


class NotificacionSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pedido_id: int
    mensaje: str
    leida: bool
    creado_en: datetime


class VentasSalida(BaseModel):
    total: Dinero
    pagos: int
