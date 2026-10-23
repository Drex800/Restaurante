"""Servicio de Pedidos: mesas, pedidos, estados de preparación, pagos y avisos."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.bootstrap import crear_tablas
from app.eventos import registrar_suscriptores
from app.routes import router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    crear_tablas()
    yield


registrar_suscriptores()

app = FastAPI(title="Servicio de Pedidos", lifespan=lifespan)
app.include_router(router)
