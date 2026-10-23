"""Servicio de Usuarios: autenticación (JWT), roles y gestión de usuarios."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.bootstrap import crear_tablas, sembrar_datos
from app.database import SessionLocal
from app.routes import router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    crear_tablas()
    with SessionLocal() as db:
        sembrar_datos(db)
    yield


app = FastAPI(title="Servicio de Usuarios", lifespan=lifespan)
app.include_router(router)
