#!/usr/bin/env bash
# Ejecuta Ruff, pytest, Bandit (y Locust si el sistema está levantado) y guarda las
# salidas en resultados/ como evidencia para la entrega.
# Uso:  ./scripts/evidencias.sh            (Ruff, pytest y Bandit)
#       CON_CARGA=1 ./scripts/evidencias.sh (además, Locust contra http://localhost)
set -u
cd "$(dirname "$0")/.."
mkdir -p resultados

if [ ! -d .venv ]; then python3 -m venv .venv; fi
# shellcheck disable=SC1091
. .venv/bin/activate
pip install -q -r usuarios/requirements-dev.txt -r productos/requirements-dev.txt \
  -r pedidos/requirements-dev.txt -r pruebas_carga/requirements.txt

fallos=0
ejecutar() { # ejecutar <archivo-de-salida> <comando...>
  local salida=$1; shift
  "$@" 2>&1 | tee "resultados/$salida"
  if [ "${PIPESTATUS[0]}" -ne 0 ]; then fallos=$((fallos + 1)); echo ">>> FALLÓ: $salida"; fi
}

for s in usuarios productos pedidos; do
  echo "=== $s ==="
  ejecutar "ruff-$s.txt"   bash -c "cd $s && ruff check . && ruff format --check ."
  ejecutar "pytest-$s.txt" bash -c "cd $s && pytest --cov=app --cov-fail-under=80"
  ejecutar "bandit-$s.txt" bash -c "cd $s && bandit -r app"
done

if [ "${CON_CARGA:-0}" = "1" ]; then
  set -a; . ./.env; set +a
  echo "=== Locust ==="
  ejecutar "locust.txt" locust -f pruebas_carga/locustfile.py --headless -u 100 -r 10 -t 30s \
    -H "${BASE_URL:-http://localhost}" --csv resultados/locust --only-summary
fi

echo
if [ "$fallos" -eq 0 ]; then echo "Todas las verificaciones pasaron. Evidencias en resultados/."; else echo "$fallos verificación(es) fallaron."; exit 1; fi
