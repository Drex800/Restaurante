"""Servicio de Productos: menú, categorías e inventario por movimientos."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.bootstrap import crear_tablas
from app.routes import router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    crear_tablas()
    yield


app = FastAPI(title="Servicio de Productos", lifespan=lifespan)
app.include_router(router)
