"""Arranque del servicio: crear tablas esperando a que PostgreSQL esté listo."""

import time

from sqlalchemy.exc import OperationalError

from app import models  # noqa: F401  (importar los modelos los registra en Base)
from app.database import Base, engine


def crear_tablas(intentos: int = 15, espera: float = 2.0) -> None:
    for intento in range(1, intentos + 1):
        try:
            Base.metadata.create_all(engine)
            return
        except OperationalError:
            if intento == intentos:
                raise
            time.sleep(espera)
