# Sistema de Gestión para Restaurante

Pedidos, cocina y caja en un solo lugar. Prototipo de **Desarrollo de Software II** construido como
**arquitectura de microservicios** con Python y FastAPI, usando solo herramientas gratuitas y de código abierto.

```
Internet → Nginx (:80) → Kong (API Gateway) → usuarios | productos | pedidos → una PostgreSQL por servicio
                         └──────────────── red privada (internal: true) ────────────────┘
```

Documentación detallada, diagramas, matriz de permisos y métricas de calidad: [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md).

## Qué hace

| Servicio | Ruta | Qué resuelve |
|---|---|---|
| **usuarios** | `/usuarios` | Login con JWT, 4 roles (ADMIN, MESERO, COCINA, CAJERO), gestión de usuarios |
| **productos** | `/productos` | Menú, categorías e inventario: el stock se calcula con movimientos (entradas, salidas, ajustes) |
| **pedidos** | `/pedidos` | Mesas, pedidos, estados (Pendiente → En preparación → Listo → Entregado), pagos validados por el cajero y aviso al cajero cuando un pedido queda listo |

## Requisitos

- Docker Engine y Docker Compose (Docker Desktop es gratuito para uso educativo).
- Para las pruebas y la calidad: Python 3.12 o superior.

## Levantar todo con un comando

```bash
cp .env.example .env        # una sola vez; cambie TODAS las claves del .env
docker compose up --build
```

Use en el `.env` solo letras, números y guiones en las contraseñas de las bases (van dentro de una URL).
Si falta alguna variable, `docker compose` se detiene y dice cuál.

Solo Nginx publica un puerto: todo se consume en `http://localhost`. Compruebe que funciona:

```bash
./scripts/verificar.sh
```

El script comprueba los `/health`, que las rutas exigen token, el login del administrador y que las bases de datos y Kong **no** son accesibles desde su equipo.

Comandos útiles: `docker compose down` conserva los datos; `docker compose down -v` **los borra**.

## Flujo de demostración

Reemplace `ADMIN_EMAIL` y `ADMIN_PASSWORD` por lo que puso en `.env`.

```bash
API=http://localhost
json() { python3 -c "import sys,json; print(json.load(sys.stdin)$1)"; }
login() { curl -s -X POST $API/usuarios/login -H 'Content-Type: application/json' \
  -d "{\"email\":\"$1\",\"password\":\"$2\"}" | json '["access_token"]'; }
post() { curl -s -X POST "$API$2" -H "Authorization: Bearer $1" -H 'Content-Type: application/json' -d "$3"; }

# 1) El administrador prepara el restaurante
ADMIN=$(login "ADMIN_EMAIL" "ADMIN_PASSWORD")
post $ADMIN /usuarios '{"nombre":"Ana","email":"ana@rest.local","password":"ClaveMesero1","rol":"MESERO"}'
post $ADMIN /usuarios '{"nombre":"Carlos","email":"carlos@rest.local","password":"ClaveCocina1","rol":"COCINA"}'
post $ADMIN /usuarios '{"nombre":"Lucia","email":"lucia@rest.local","password":"ClaveCajero1","rol":"CAJERO"}'
post $ADMIN /productos/categorias '{"nombre":"Platos fuertes"}'
post $ADMIN /productos '{"nombre":"Bandeja paisa","precio":32000,"categoria_id":1}'
post $ADMIN /productos/1/movimientos '{"tipo":"ENTRADA","cantidad":20,"motivo":"Compra inicial"}'
post $ADMIN /pedidos/mesas '{"numero":1,"capacidad":4}'

# 2) La mesera crea el pedido (se descuenta el inventario)
MESERO=$(login ana@rest.local ClaveMesero1)
post $MESERO /pedidos '{"mesa_id":1,"items":[{"producto_id":1,"cantidad":2,"nota":"sin cebolla"}]}'

# 3) Cocina prepara; al quedar listo, el cajero recibe el aviso
COCINA=$(login carlos@rest.local ClaveCocina1)
curl -s "$API/pedidos?estado=PENDIENTE" -H "Authorization: Bearer $COCINA"
for e in EN_PREPARACION LISTO; do
  curl -s -X PATCH $API/pedidos/1/estado -H "Authorization: Bearer $COCINA" \
    -H 'Content-Type: application/json' -d "{\"estado\":\"$e\"}" > /dev/null
done

# 4) El cajero ve el aviso y valida el pago (el monto debe ser igual al total)
CAJERO=$(login lucia@rest.local ClaveCajero1)
curl -s $API/pedidos/notificaciones -H "Authorization: Bearer $CAJERO"
post $CAJERO /pedidos/1/pago '{"monto":64000,"metodo":"EFECTIVO"}'

# 5) El administrador consulta las ventas
curl -s $API/pedidos/ventas -H "Authorization: Bearer $ADMIN"
```

La documentación interactiva de cada servicio (Swagger) no se publica porque los servicios están en la red privada; para verla durante el desarrollo se puede publicar temporalmente un puerto en un `docker-compose.override.yml` local que **no** se sube a Git.

## Pruebas y calidad

Cada servicio se verifica por separado (carpeta `usuarios/`, `productos/` o `pedidos/`):

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

ruff format .                              # una vez, para dar formato al código
ruff check . && ruff format --check .      # estilo y errores, sin advertencias
pytest --cov=app --cov-fail-under=80       # pruebas de cada endpoint, cobertura ≥ 80 %
bandit -r app                              # sin vulnerabilidades críticas
```

Las pruebas usan SQLite en memoria y un doble del servicio de productos, así que no necesitan Docker.

Todo junto, guardando las evidencias en `resultados/`:

```bash
./scripts/evidencias.sh                    # Ruff, pytest y Bandit de los 3 servicios
CON_CARGA=1 ./scripts/evidencias.sh        # además Locust (el sistema debe estar levantado)
```

Prueba de carga (criterio: p95 ≤ 2 s con 100 usuarios y 0 fallos):

```bash
pip install -r pruebas_carga/requirements.txt
set -a; . ./.env; set +a
locust -f pruebas_carga/locustfile.py --headless -u 100 -r 10 -t 30s -H http://localhost
```

La integración continua (`.github/workflows/ci.yml`) repite Ruff, pytest, Bandit y la validación del compose en cada push.

## Estructura

```
restaurante/
├─ docker-compose.yml        # 8 contenedores, red privada interna, un volumen por base
├─ .env.example              # variables y secretos (el .env real no va a Git)
├─ nginx/nginx.conf          # load balancer → kong
├─ kong/kong.yml             # rutas /usuarios, /productos, /pedidos (modo DB-less)
├─ usuarios/   productos/   pedidos/
│   ├─ app/                  # main.py, routes.py, models.py, schemas.py, security.py, …
│   ├─ tests/
│   ├─ requirements.txt  requirements-dev.txt  pyproject.toml
│   └─ Dockerfile
├─ pruebas_carga/locustfile.py
├─ scripts/verificar.sh  scripts/evidencias.sh
└─ docs/ARQUITECTURA.md
```

## Estado de la verificación

Este repositorio se escribió en un entorno sin acceso a PyPI ni a Docker Hub, así que **antes de entregar hay que ejecutar** los comandos de arriba en su equipo. Lo que sí se comprobó:

- Todos los archivos Python compilan y los YAML (Kong, compose, CI) son válidos.
- `docker compose config` acepta el `docker-compose.yml` con el `.env.example` y rechaza la ejecución si falta una variable.

Lo que **no** se ha ejecutado todavía: `docker compose up --build`, pytest, Ruff, Bandit y Locust. Si alguna prueba falla en su equipo, es un error del código y conviene corregirlo (por ejemplo, el formato: ejecute `ruff format .` una vez).

## Pendientes

Frontend Angular, migraciones con Alembic, copias de seguridad por base y HTTPS en Nginx. Detalle en la sección 10 de [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md).
