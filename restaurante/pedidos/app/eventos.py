"""Bus de eventos en memoria (versión ligera de la arquitectura orientada a eventos).

El servicio de pedidos publica un evento cuando algo importante ocurre y los
interesados reaccionan. No hay Kafka: este servicio es un solo proceso y la base
de datos sigue siendo la fuente de verdad.
"""

import logging
from collections import defaultdict
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.models import Notificacion

logger = logging.getLogger("pedidos.eventos")

PEDIDO_CREADO = "pedido.creado"
PEDIDO_ESTADO_CAMBIADO = "pedido.estado_cambiado"
PEDIDO_LISTO = "pedido.listo"

Manejador = Callable[[Session, dict], None]
_suscriptores: dict[str, list[Manejador]] = defaultdict(list)


def suscribir(evento: str, manejador: Manejador) -> None:
    if manejador not in _suscriptores[evento]:
        _suscriptores[evento].append(manejador)


def publicar(evento: str, db: Session, datos: dict) -> None:
    for manejador in _suscriptores[evento]:
        try:
            manejador(db, datos)
        except Exception:
            # Un suscriptor con error no debe tumbar la operación principal.
            logger.exception("Falló el manejador %s del evento %s", manejador.__name__, evento)


# ---------- suscriptores ----------
def notificar_al_cajero(db: Session, datos: dict) -> None:
    db.add(
        Notificacion(
            pedido_id=datos["pedido_id"],
            mensaje=f"Pedido #{datos['pedido_id']} listo (mesa {datos['mesa_numero']})",
        )
    )
    db.commit()


def auditar(_db: Session, datos: dict) -> None:
    logger.info(
        "AUDITORIA pedido=%s estado=%s usuario=%s",
        datos["pedido_id"],
        datos.get("estado", "CREADO"),
        datos.get("usuario_id"),
    )


def registrar_suscriptores() -> None:
    suscribir(PEDIDO_LISTO, notificar_al_cajero)
    suscribir(PEDIDO_CREADO, auditar)
    suscribir(PEDIDO_ESTADO_CAMBIADO, auditar)
