"""Roles del sistema: cada usuario tiene exactamente uno."""

from typing import Literal

ADMIN = "ADMIN"
MESERO = "MESERO"
COCINA = "COCINA"
CAJERO = "CAJERO"

ROLES = (ADMIN, MESERO, COCINA, CAJERO)

NombreRol = Literal["ADMIN", "MESERO", "COCINA", "CAJERO"]
