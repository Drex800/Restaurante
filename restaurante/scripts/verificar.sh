#!/usr/bin/env bash
# Verifica que la arquitectura levantada con `docker compose up --build` funciona.
# Uso:  ./scripts/verificar.sh            (lee ADMIN_EMAIL y ADMIN_PASSWORD de .env)
set -u

BASE="${BASE_URL:-http://localhost}"
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

fallos=0
ok()   { printf '  [OK]    %s\n' "$1"; }
mal()  { printf '  [FALLA] %s\n' "$1"; fallos=$((fallos + 1)); }

codigo() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

esperar() {
  local verificado=$1 cod
  for _ in $(seq 1 30); do
    cod=$(codigo "$BASE/$verificado/health")
    [ "$cod" = "200" ] && return 0
    sleep 2
  done
  return 1
}

echo "1) Servicios detrás de Nginx → Kong"
for s in usuarios productos pedidos; do
  if esperar "$s"; then ok "$BASE/$s/health responde 200"; else mal "$BASE/$s/health no responde 200"; fi
done

echo "2) Las rutas protegidas exigen token"
[ "$(codigo "$BASE/usuarios")" = "401" ] && ok "GET /usuarios sin token → 401" || mal "GET /usuarios sin token debería ser 401"
[ "$(codigo "$BASE/productos")" = "401" ] && ok "GET /productos sin token → 401" || mal "GET /productos sin token debería ser 401"
[ "$(codigo "$BASE/pedidos")" = "401" ] && ok "GET /pedidos sin token → 401" || mal "GET /pedidos sin token debería ser 401"

echo "3) Login y consulta con token"
TOKEN=$(curl -s -X POST "$BASE/usuarios/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"${ADMIN_EMAIL:-}\",\"password\":\"${ADMIN_PASSWORD:-}\"}" \
  | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
if [ -n "$TOKEN" ]; then ok "login del administrador devuelve un token"; else mal "no se obtuvo token (revise ADMIN_EMAIL / ADMIN_PASSWORD)"; fi
for ruta in usuarios productos pedidos; do
  [ "$(codigo -H "Authorization: Bearer $TOKEN" "$BASE/$ruta")" = "200" ] \
    && ok "GET /$ruta con token → 200" || mal "GET /$ruta con token debería ser 200"
done

echo "4) Las bases de datos no están expuestas"
for puerto in 5432 5433 5434; do
  if (exec 3<>"/dev/tcp/127.0.0.1/$puerto") 2>/dev/null; then
    mal "el puerto $puerto del equipo anfitrión está abierto"
  else
    ok "puerto $puerto: conexión rechazada"
  fi
done

echo "5) Kong no es accesible desde fuera (solo Nginx publica un puerto)"
if (exec 3<>"/dev/tcp/127.0.0.1/8000") 2>/dev/null; then mal "el puerto 8000 está abierto"; else ok "puerto 8000: conexión rechazada"; fi

echo
if [ "$fallos" -eq 0 ]; then echo "Todo correcto."; else echo "$fallos verificación(es) fallaron."; exit 1; fi
