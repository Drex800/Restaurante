"""Conexión a la base de datos propia del servicio de pedidos."""

import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.environ["DATABASE_URL"]

_opciones: dict = {}
if DATABASE_URL.startswith("sqlite"):
    # SQLite solo se usa en pruebas automáticas (en memoria).
    _opciones = {
        "connect_args": {"check_same_thread": False},
        "poolclass": StaticPool,
    }

engine = create_engine(DATABASE_URL, pool_pre_ping=True, **_opciones)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
