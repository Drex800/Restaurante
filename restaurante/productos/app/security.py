"""Validación de tokens JWT emitidos por el servicio de usuarios.

Este servicio no consulta la base de datos de usuarios: solo verifica la firma
del token con el secreto compartido y lee el rol que trae dentro.
"""

import hmac
import os
from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.roles import ADMIN

ALGORITMO = "HS256"
bearer = HTTPBearer(auto_error=False)


def _secreto() -> str:
    return os.environ["JWT_SECRET"]


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


def autorizar_movimiento(
    credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    x_service_token: Annotated[str | None, Header()] = None,
) -> str:
    """Los movimientos de inventario los registra un administrador o, para las
    salidas automáticas, el servicio de pedidos con el token de servicio."""
    if x_service_token is not None:
        esperado = os.environ.get("SERVICE_TOKEN", "")
        if esperado and hmac.compare_digest(x_service_token, esperado):
            return "servicio"
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de servicio inválido")
    actual = usuario_actual(credenciales)
    if actual.get("rol") != ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tiene permiso para esta acción")
    return f"usuario:{actual['sub']}"
