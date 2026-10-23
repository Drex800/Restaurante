"""Contraseñas y tokens JWT. Los permisos se validan siempre en el backend."""

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

ALGORITMO = "HS256"
bearer = HTTPBearer(auto_error=False)


def _secreto() -> str:
    return os.environ["JWT_SECRET"]


def _bytes(password: str) -> bytes:
    # bcrypt solo considera los primeros 72 bytes.
    return password.encode("utf-8")[:72]


def hashear(password: str) -> str:
    rondas = int(os.environ.get("BCRYPT_ROUNDS", "12"))
    return bcrypt.hashpw(_bytes(password), bcrypt.gensalt(rounds=rondas)).decode("ascii")


def verificar(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(_bytes(password), password_hash.encode("ascii"))


def crear_token(usuario_id: int, rol: str) -> str:
    minutos = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))
    carga = {
        "sub": str(usuario_id),
        "rol": rol,
        "exp": datetime.now(UTC) + timedelta(minutes=minutos),
    }
    return jwt.encode(carga, _secreto(), algorithm=ALGORITMO)


def usuario_actual(
    credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> dict:
    """Devuelve la carga del token (sub, rol) o responde 401."""
    if credenciales is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falta el token de acceso")
    try:
        return jwt.decode(credenciales.credentials, _secreto(), algorithms=[ALGORITMO])
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido o vencido") from exc


def requiere_roles(*roles: str) -> Callable[..., dict]:
    """Fabrica una dependencia que exige uno de los roles indicados (403 si no)."""

    def dependencia(actual: Annotated[dict, Depends(usuario_actual)]) -> dict:
        if actual.get("rol") not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No tiene permiso para esta acción")
        return actual

    return dependencia
