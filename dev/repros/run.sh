#!/usr/bin/env bash
# Reproduce un error de c_errorstfix.md.
#
# uso (desde la raiz del repositorio):
#   bash dev/repros/run.sh <programa> [i] [c] [w] [v1]
#
#   <programa>  nombre sin '.srcx' (p. ej. vm_mem_take, limites/l05_for)
#   i   V0 + interprete     (python V0/main.py prog --run interpreter)
#   c   V0 + VM             (python V0/main.py prog --run compiler)
#   w   V0 + target web     (--emit-hir y node web/main.ts prog.phir --run)
#   v1  la V1 compilando el programa (la VM tiene que estar construida)
#
# Sin motores corre 'i c'. El programa se copia a una carpeta temporal, asi
# que no deja 'dumps/' ni 'log/' en el repositorio. Se quitan de la salida
# las lineas de progreso del compilador ('frontend OK', 'HIR (...)').
set -u
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
export PYTHONUTF8=1
# node no siempre esta en el PATH en Windows
[ -d "/c/Program Files/nodejs" ] && export PATH="/c/Program Files/nodejs:$PATH"

nombre="$1"; shift
motores="${*:-i c}"
fuente="$REPO/dev/repros/$nombre.srcx"
[ -f "$fuente" ] || { echo "no existe $fuente"; exit 2; }
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
base="$(basename "$nombre")"
cp "$fuente" "$tmp/$base.srcx"
cd "$tmp"

filtro() { grep -v -E "^  unidad|^HIR \(|^frontend OK|diagnosticos registrados"; }

for m in $motores; do
  case "$m" in
    i|c)
      motor=$([ "$m" = i ] && echo interpreter || echo compiler)
      echo "--- $base [$motor]"
      python "$REPO/V0/main.py" "$base.srcx" --run "$motor" 2>&1 | filtro
      echo "exit=${PIPESTATUS[0]}" ;;
    w)
      echo "--- $base [web]"
      python "$REPO/V0/main.py" "$base.srcx" --emit-hir >/dev/null 2>&1
      node "$REPO/web/main.ts" "dumps/$base.srcx.phir" --run 2>&1
      echo "exit=$?" ;;
    v1)
      echo "--- $base [V1]"
      vm="$REPO/build/bin/suriax-hir"
      [ -x "$vm" ] || [ -x "$vm.exe" ] || { echo "falta la VM: ver how_to_run.md"; continue; }
      mkdir -p v1/lib
      cp -r "$REPO/lib/." v1/lib/
      for p in frontend semantica hir; do cp -r "$REPO/src/$p" v1/lib/; done
      cp "$REPO/src/main.srcx" v1/
      printf 'version: 1\ntarget: native\n' > v1/.suriaX_config.yaml
      (cd v1 && python "$REPO/V0/main.py" main.srcx --emit-hir >/dev/null 2>&1)
      cp "$base.srcx" v1/
      (cd v1 && "$vm" dumps/main.srcx.phir --run --quiet -- "$base.srcx" salida.phir 2>&1)
      echo "exit=$?" ;;
    *) echo "motor desconocido: $m (usa i, c, w o v1)" ;;
  esac
done
