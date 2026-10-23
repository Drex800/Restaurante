"""Esquemas de entrada y salida de la API de productos."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

# El dinero se maneja como Decimal y se entrega como número JSON.
Dinero = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]

TipoMovimiento = Literal["ENTRADA", "SALIDA", "AJUSTE"]


class CategoriaCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)


class CategoriaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str


class ProductoCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    descripcion: str | None = Field(default=None, max_length=300)
    precio: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    categoria_id: int


class ProductoActualizar(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=120)
    descripcion: str | None = Field(default=None, max_length=300)
    precio: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    categoria_id: int | None = None
    activo: bool | None = None


class ProductoSalida(BaseModel):
    id: int
    nombre: str
    descripcion: str | None
    precio: Dinero
    activo: bool
    categoria_id: int
    stock: int


class MovimientoCrear(BaseModel):
    tipo: TipoMovimiento
    cantidad: int = Field(description="Positiva en ENTRADA y SALIDA; con signo en AJUSTE")
    motivo: str | None = Field(default=None, max_length=200)


class MovimientoSalida(BaseModel):
    id: int
    producto_id: int
    tipo: str
    cantidad: int
    motivo: str | None
    registrado_por: str
    creado_en: datetime
    stock_resultante: int
