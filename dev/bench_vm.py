#!/usr/bin/env python3
"""Banco de medida: intérprete tree-walk (Python) contra la VM de registros (C++).

No es un test (no falla ni pasa): es el instrumento con el que se sostiene
la decisión de tener una VM, documentada en
``documentation/source/vm_decision.rst``. Sirve para repetir la medición en
otra máquina o después de un cambio, con la misma metodología:

- El frontend compila CADA programa UNA vez a ``.phir``. Los dos motores
  ejecutan ESE archivo, así que se compara la ejecución y no el compilador.
- Se mide de punta a punta como lo vería un usuario: arrancar el proceso,
  leer el ``.phir`` y sus librerías, ligar, (la VM además baja al MIR y lo
  verifica) y ejecutar. El programa ``vacio`` da el costo FIJO de cada motor,
  que se resta para obtener el tiempo NETO de ejecución.
- Cada medida se repite y se informa la MEDIANA (y el mínimo): una sola
  corrida en Windows mide también al antivirus.
- Antes de comparar tiempos se comprueba que los dos motores imprimieron LO
  MISMO. Un tiempo de un programa que dio otra salida no significa nada, y
  el banco lo reporta como error en vez de como número.

Uso::

    python dev/bench_vm.py                     # todo, 3 repeticiones
    python dev/bench_vm.py fib criba           # solo esos programas
    python dev/bench_vm.py --repeticiones 5
    python dev/bench_vm.py --json medida.json  # además, para máquinas
    SURIAX_HIR_BIN=/ruta/suriax-hir python dev/bench_vm.py

La VM se construye antes con CMake (ver ``CMake/README.md``); sin el binario
el banco lo dice y termina.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Dict, List, Optional, Tuple

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROGRAMAS = os.path.join(_REPO, "dev", "bench_vm")
_FRONTEND = os.path.join(_REPO, "src", "frontend")
_MAIN = os.path.join(_REPO, "main.py")
_INTERP = os.path.join(_REPO, "runtime", "interpreter", "main.py")
_ENV = {**os.environ, "PYTHONUTF8": "1"}

#: programas escritos a mano, en el orden en que se informan
_SIMPLES = ("vacio", "bucle", "fib", "criba", "cadenas", "vector")

#: cargas REALES: el frontend del bootstrap (escrito en suriaX) leyendo un
#: archivo suyo. Es el programa grande que el proyecto tiene, y el que decide
#: si el compilador escrito en suriaX es usable.
_BOOTSTRAP = {
    "lexer": ("lexer.libsrx", "tokeniza"),
    "parser": ("expresiones.libsrx", "analiza"),
}


def _binario_vm() -> Optional[str]:
    ruta = os.environ.get("SURIAX_HIR_BIN")
    candidatos = [ruta] if ruta else [
        os.path.join(_REPO, d, "bin", "suriax-hir" + ext)
        for d in ("build", "build-msvc") for ext in ("", ".exe")]
    for c in candidatos:
        if c and os.path.isfile(c):
            return c
    return None


def _literal(texto: str) -> str:
    """Un archivo entero como literal de cadena de suriaX."""
    return (texto.replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r"))


def _fuente_bootstrap(archivo: str, modo: str) -> str:
    texto = open(os.path.join(_FRONTEND, archivo), encoding="utf-8").read()
    if modo == "tokeniza":
        return ("#from io #import stdp\n"
                "#import frontend.lexer as lx\n"
                "#import array.vector as vec\n"
                "fn main() -> int {\n"
                "    var vec.Vector<str> errores = vec.dynamic<str>(4);\n"
                f'    var int n = lx.tokenizar("{_literal(texto)}", &errores).len();\n'
                '    stdp.println(f"{n} tokens, {errores.len()} errores");\n'
                "    return 0;\n"
                "}\n")
    return ("#import frontend.parser as ps\n"
            "fn main() -> int {\n"
            f'    ps.analiza("{_literal(texto)}");\n'
            "    return 0;\n"
            "}\n")


def _prepara(nombre: str, destino: str) -> str:
    """Arma el proyecto de un programa en 'destino' y devuelve su fuente."""
    shutil.copytree(os.path.join(_REPO, "lib"), os.path.join(destino, "lib"))
    fuente = os.path.join(destino, nombre + ".srcx")
    if nombre in _BOOTSTRAP:
        shutil.copytree(_FRONTEND, os.path.join(destino, "lib", "frontend"))
        archivo, modo = _BOOTSTRAP[nombre]
        with open(fuente, "w", encoding="utf-8") as fh:
            fh.write(_fuente_bootstrap(archivo, modo))
    else:
        shutil.copy(os.path.join(_PROGRAMAS, nombre + ".srcx"), fuente)
    # 'native': el frontend emite las unidades de librería junto al .phir,
    # que es donde las buscan los dos motores
    with open(os.path.join(destino, ".suriaX_config.yaml"), "w", encoding="utf-8") as fh:
        fh.write("version: 1\ntarget: native\n")
    return fuente


def _tiempo_del_frontend(texto: str) -> Optional[float]:
    """El tiempo de COMPILAR, en segundos, leído de ``--time``.

    Es el ``TOTAL`` menos la fase ``interprete``: cuando el target efectivo es
    ``interp`` (el de por defecto, y el que queda si falta pyyaml para leer
    el yaml), ``--emit-hir`` además EJECUTA el programa, y medir el proceso
    entero habría contado la ejecución como compilación.
    """
    fases = {m.group(1): float(m.group(2)) for m in
             re.finditer(r"^\s+(\S+)\s+([\d.]+) ms$", texto, re.MULTILINE)}
    if "TOTAL" not in fases:
        return None
    return (fases["TOTAL"] - fases.get("interprete", 0.0)) / 1000.0


def _salida(stdout: str) -> List[str]:
    """Lo que imprimió el PROGRAMA, sin lo que dicen los motores."""
    return [l for l in stdout.splitlines()
            if not l.startswith(("frontend OK", "HIR ", "[exit]", "[vm] main() -> "))
            and not (l.lstrip().startswith("unidad '") and " -> " in l)]


def _mide(comando: List[str], cwd: str, repeticiones: int
          ) -> Tuple[List[float], subprocess.CompletedProcess]:
    tiempos = []
    ultima = None
    for _ in range(repeticiones):
        inicio = time.perf_counter()
        ultima = subprocess.run(comando, cwd=cwd, capture_output=True,
                                encoding="utf-8", errors="replace", env=_ENV,
                                timeout=3600)
        tiempos.append(time.perf_counter() - inicio)
    return tiempos, ultima


def _corre(nombre: str, vm: str, repeticiones: int) -> Dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="bench-vm-") as tmp:
        fuente = _prepara(nombre, tmp)
        phir = os.path.join(tmp, "prog.phir")
        emit = subprocess.run([sys.executable, _MAIN, fuente, "--emit-hir", phir,
                               "--time"],
                              cwd=tmp, capture_output=True, encoding="utf-8",
                              errors="replace", env=_ENV)
        compilar = _tiempo_del_frontend(emit.stdout + emit.stderr)
        if not os.path.isfile(phir):
            return {"programa": nombre, "error": "no compila: " +
                    (emit.stdout + emit.stderr)[-400:]}
        t_interp, interp = _mide([sys.executable, _INTERP, phir, "--exec"], tmp,
                                 repeticiones)
        t_vm, maquina = _mide([vm, phir, "--run"], tmp, repeticiones)
        fila: Dict[str, object] = {
            "programa": nombre,
            "compilar_s": compilar,
            "interprete_s": t_interp,
            "vm_s": t_vm,
            "salida": _salida(interp.stdout)[:3],
        }
        if interp.returncode != maquina.returncode or \
                _salida(interp.stdout) != _salida(maquina.stdout):
            fila["error"] = (
                f"los motores no coinciden (exit {interp.returncode} vs "
                f"{maquina.returncode}): intérprete={_salida(interp.stdout)[:2]} "
                f"{interp.stderr[-200:]!r} | vm={_salida(maquina.stdout)[:2]} "
                f"{maquina.stderr[-200:]!r}")
        return fila


def _entorno(vm: str) -> Dict[str, str]:
    return {
        "sistema": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "procesador": platform.processor() or "desconocido",
        "python": platform.python_version(),
        "vm": os.path.relpath(vm, _REPO),
    }


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="bench_vm", description=__doc__.split("\n")[0])
    parser.add_argument("programas", nargs="*",
                        help=f"subconjunto de {list(_SIMPLES) + list(_BOOTSTRAP)}")
    parser.add_argument("--repeticiones", type=int, default=3)
    parser.add_argument("--json", metavar="ARCHIVO")
    args = parser.parse_args(argv[1:])

    vm = _binario_vm()
    if vm is None:
        print("no está construido 'suriax-hir': cmake -S . -B build && "
              "cmake --build build --target suriax-hir (o SURIAX_HIR_BIN)",
              file=sys.stderr)
        return 2
    todos = list(_SIMPLES) + list(_BOOTSTRAP)
    pedidos = args.programas or todos
    desconocidos = [p for p in pedidos if p not in todos]
    if desconocidos:
        print(f"programas desconocidos: {desconocidos}; hay {todos}", file=sys.stderr)
        return 2
    # el vacío siempre: es la referencia que se resta
    if "vacio" not in pedidos:
        pedidos = ["vacio"] + pedidos

    entorno = _entorno(vm)
    for clave, valor in entorno.items():
        print(f"{clave:11} {valor}")
    print(f"{'repeticiones':11} {args.repeticiones} (se informa la mediana)\n")

    filas = []
    for nombre in pedidos:
        print(f"  midiendo {nombre}...", file=sys.stderr, flush=True)
        filas.append(_corre(nombre, vm, args.repeticiones))

    base = next(f for f in filas if f["programa"] == "vacio")
    fijo_i = statistics.median(base.get("interprete_s", [0.0]))
    fijo_v = statistics.median(base.get("vm_s", [0.0]))

    cabecera = (f"{'programa':9} {'frontend':>9} {'intérprete':>11} {'VM':>9} "
                f"{'neto int.':>10} {'neto VM':>9} {'aceleración':>12}")
    print(cabecera)
    print("-" * len(cabecera))
    hubo_error = False
    for f in filas:
        if "error" in f:
            hubo_error = True
            print(f"{f['programa']:9} ERROR: {f['error']}")
            continue
        ti = statistics.median(f["interprete_s"])
        tv = statistics.median(f["vm_s"])
        ni = max(ti - fijo_i, 0.0)
        nv = max(tv - fijo_v, 0.0)
        # la aceleracion NETA: la de la ejecucion, sin el arranque
        acel = f"{ni / nv:10.1f}x" if nv > 0.0005 and f["programa"] != "vacio" else "—"
        f["neto_interprete_s"] = ni
        f["neto_vm_s"] = nv
        fe = f"{f['compilar_s']:8.3f}s" if f.get("compilar_s") is not None else f"{'?':>9}"
        print(f"{f['programa']:9} {fe} {ti:10.3f}s {tv:8.3f}s {ni:9.3f}s {nv:8.3f}s {acel:>12}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"entorno": entorno, "repeticiones": args.repeticiones,
                       "filas": filas}, fh, ensure_ascii=False, indent=2)
    return 1 if hubo_error else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
