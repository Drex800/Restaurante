"""Endpoints del servicio de usuarios."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app.models import Rol, Usuario
from app.roles import ADMIN
from app.schemas import LoginEntrada, TokenSalida, UsuarioCrear, UsuarioSalida
from app.security import (
    crear_token,
    hashear,
    requiere_roles,
    usuario_actual,
    verificar,
)

router = APIRouter(prefix="/usuarios", tags=["usuarios"])

DB = Annotated[Session, Depends(get_db)]
Autenticado = Annotated[dict, Depends(usuario_actual)]
Admin = Annotated[dict, Depends(requiere_roles(ADMIN))]


def _salida(usuario: Usuario) -> UsuarioSalida:
    return UsuarioSalida(
        id=usuario.id,
        nombre=usuario.nombre,
        email=usuario.email,
        rol=usuario.rol.nombre,
        activo=usuario.activo,
    )


def _buscar(db: Session, usuario_id: int) -> Usuario:
    usuario = db.get(Usuario, usuario_id)
    if usuario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")
    return usuario


@router.get("/health")
def health() -> dict:
    try:
        with engine.connect() as conexion:
            conexion.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Base de datos no disponible"
        ) from exc
    return {"status": "ok"}


@router.post("/login", response_model=TokenSalida)
def login(datos: LoginEntrada, db: DB) -> TokenSalida:
    usuario = db.scalar(select(Usuario).where(Usuario.email == datos.email))
    if (
        usuario is None
        or not usuario.activo
        or not verificar(datos.password, usuario.password_hash)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales inválidas")
    return TokenSalida(access_token=crear_token(usuario.id, usuario.rol.nombre))


@router.get("/me", response_model=UsuarioSalida)
def yo(actual: Autenticado, db: DB) -> UsuarioSalida:
    return _salida(_buscar(db, int(actual["sub"])))


@router.get("", response_model=list[UsuarioSalida])
def listar(_: Admin, db: DB) -> list[UsuarioSalida]:
    return [_salida(u) for u in db.scalars(select(Usuario).order_by(Usuario.id))]


@router.post("", response_model=UsuarioSalida, status_code=status.HTTP_201_CREATED)
def crear(datos: UsuarioCrear, _: Admin, db: DB) -> UsuarioSalida:
    if db.scalar(select(Usuario).where(Usuario.email == datos.email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un usuario con ese correo")
    rol = db.scalar(select(Rol).where(Rol.nombre == datos.rol))
    usuario = Usuario(
        nombre=datos.nombre,
        email=datos.email,
        password_hash=hashear(datos.password),
        rol_id=rol.id,
    )
    db.add(usuario)
    db.commit()
    return _salida(usuario)


@router.get("/{usuario_id}", response_model=UsuarioSalida)
def obtener(usuario_id: int, _: Admin, db: DB) -> UsuarioSalida:
    return _salida(_buscar(db, usuario_id))


@router.delete("/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar(usuario_id: int, actual: Admin, db: DB) -> Response:
    if usuario_id == int(actual["sub"]):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No puede desactivarse a sí mismo")
    usuario = _buscar(db, usuario_id)
    usuario.activo = False
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
