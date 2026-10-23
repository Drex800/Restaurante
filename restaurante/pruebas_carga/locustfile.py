"""Prueba de carga con Locust contra la arquitectura completa (Nginx → Kong → servicios).

Criterio de aceptación: con 100 usuarios, tiempo de respuesta (percentil 95) <= 2 s y 0 fallos.

    ADMIN_EMAIL=... ADMIN_PASSWORD=... \
    locust -f pruebas_carga/locustfile.py --headless -u 100 -r 10 -t 30s -H http://localhost
"""

import os

import requests
from locust import HttpUser, between, events, task

LIMITE_P95_MS = 2000
_token = {"valor": None}


@events.test_start.add_listener
def iniciar_sesion_una_vez(environment, **_kwargs):
    """Un único login para toda la prueba: así se mide el sistema, no el cifrado bcrypt."""
    respuesta = requests.post(
        f"{environment.host}/usuarios/login",
        json={
            "email": os.environ["ADMIN_EMAIL"],
            "password": os.environ["ADMIN_PASSWORD"],
        },
        timeout=10,
    )
    respuesta.raise_for_status()
    _token["valor"] = respuesta.json()["access_token"]


@events.quitting.add_listener
def validar_criterios(environment, **_kwargs):
    total = environment.stats.total
    p95 = total.get_response_time_percentile(0.95) or 0
    if total.num_failures > 0 or p95 > LIMITE_P95_MS:
        print(f"CRITERIO NO CUMPLIDO: fallos={total.num_failures}, p95={p95} ms")
        environment.process_exit_code = 1
    else:
        print(f"CRITERIO CUMPLIDO: 0 fallos y p95={p95} ms <= {LIMITE_P95_MS} ms")


class Cliente(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        self.headers = {"Authorization": f"Bearer {_token['valor']}"}

    @task(3)
    def ver_menu(self):
        self.client.get("/productos", headers=self.headers)

    @task(3)
    def ver_tablero_de_pedidos(self):
        self.client.get("/pedidos", headers=self.headers)

    @task(2)
    def ver_mesas(self):
        self.client.get("/pedidos/mesas", headers=self.headers)

    @task(1)
    def ver_perfil(self):
        self.client.get("/usuarios/me", headers=self.headers)

    @task(1)
    def health_de_los_servicios(self):
        for ruta in ("/usuarios/health", "/productos/health", "/pedidos/health"):
            self.client.get(ruta)
