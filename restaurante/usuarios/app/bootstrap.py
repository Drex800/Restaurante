"""Arranque del servicio: crear tablas, sembrar roles y el administrador inicial."""

import os
import time

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.database import Base, engine
from app.models import Rol, Usuario
from app.roles import ADMIN, ROLES
from app.security import hashear


def crear_tablas(intentos: int = 15, espera: float = 2.0) -> None:
    """Crea las tablas; reintenta mientras PostgreSQL termina de arrancar."""
    for intento in range(1, intentos + 1):
        try:
            Base.metadata.create_all(engine)
            return
        except OperationalError:
            if intento == intentos:
                raise
            time.sleep(espera)


def sembrar_datos(db: Session) -> None:
    existentes = set(db.scalars(select(Rol.nombre)))
    for nombre in ROLES:
        if nombre not in existentes:
            db.add(Rol(nombre=nombre))
    db.commit()

    email = os.environ.get("ADMIN_EMAIL")
    clave = os.environ.get("ADMIN_PASSWORD")
    if not email or not clave:
        return
    if db.scalar(select(Usuario).where(Usuario.email == email)) is not None:
        return
    rol_admin = db.scalar(select(Rol).where(Rol.nombre == ADMIN))
    db.add(
        Usuario(
            nombre="Administrador",
            email=email,
            password_hash=hashear(clave),
            rol_id=rol_admin.id,
        )
    )
    db.commit()
