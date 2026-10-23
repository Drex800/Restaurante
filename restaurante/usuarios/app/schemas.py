"""Esquemas de entrada y salida de la API de usuarios."""

from pydantic import BaseModel, Field

from app.roles import NombreRol

PATRON_EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class LoginEntrada(BaseModel):
    email: str = Field(pattern=PATRON_EMAIL, max_length=150)
    password: str = Field(min_length=1, max_length=72)


class TokenSalida(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UsuarioCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    email: str = Field(pattern=PATRON_EMAIL, max_length=150)
    password: str = Field(min_length=8, max_length=72)
    rol: NombreRol


class UsuarioSalida(BaseModel):
    id: int
    nombre: str
    email: str
    rol: str
    activo: bool
