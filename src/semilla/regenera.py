"""Regenera la SEMILLA: la V2, el compilador de suriaX compilado por sí mismo.

    python src/semilla/regenera.py [--desde-v0] [--vm <suriax-hir>]

Sin ``--desde-v0`` NO usa la V0: la semilla actual compila la V1 de hoy
(``src/``), y lo que sale se compila otra vez a sí mismo. Las dos salidas
tienen que ser idénticas (el punto fijo); recién entonces reemplazan a la
semilla. Python solo arma la carpeta y llama a la VM: el compilador que
trabaja es la propia semilla.

``--desde-v0`` arranca de la V0 (``V0/main.py``): para la primera semilla, o
cuando la actual ya no puede compilar el fuente (un cambio del esquema del
HIR que ella no conoce).

El proyecto se arma SIEMPRE con la misma forma (``main.srcx``, ``lib/`` con
la stdlib y los paquetes de la V1, un ``.suriaX_config.yaml``), la misma que
usan las pruebas: las rutas que viajan en cada ``.phir`` son relativas a esa
raíz, así que la semilla no depende de dónde ni en qué máquina se genera.
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(AQUI)
REPO = os.path.dirname(SRC)
PAQUETES = ("frontend", "semantica", "hir")


def vm_por_defecto() -> str:
    """``SURIAX_HIR_BIN`` o el ``suriax-hir`` de una carpeta ``build*``."""
    desde_entorno = os.environ.get("SURIAX_HIR_BIN")
    if desde_entorno:
        return desde_entorno
    for patron in ("build*/bin/suriax-hir.exe", "build*/bin/suriax-hir",
                   "build*/*/suriax-hir.exe", "build*/suriax-hir"):
        for candidato in sorted(glob.glob(os.path.join(REPO, patron))):
            if "asan" not in candidato and os.path.isfile(candidato):
                return candidato
    sys.exit("no se encontró 'suriax-hir': constrúyelo (cmake --build build --target "
             "suriax-hir) o pásalo con --vm")


def arma_proyecto(destino: str) -> None:
    """La forma canónica: la misma que arman las pruebas del bootstrap."""
    shutil.copytree(os.path.join(REPO, "lib"), os.path.join(destino, "lib"))
    for paquete in PAQUETES:
        shutil.copytree(os.path.join(SRC, paquete), os.path.join(destino, "lib", paquete))
    shutil.copy(os.path.join(SRC, "main.srcx"), destino)
    with open(os.path.join(destino, ".suriaX_config.yaml"), "w", encoding="utf-8") as fh:
        fh.write("version: 1\ntarget: native\n")


def compila(vm: str, compilador: str, salida: str, proyecto: str) -> None:
    """``compilador`` (un .phir) compila la V1 del proyecto en ``salida``."""
    hecho = subprocess.run([vm, compilador, "--run", "--quiet", "--pasos", "0", "--",
                            "main.srcx", os.path.join(salida, "main.srcx.phir"),
                            "--stdlib", os.path.join(REPO, "lib")],
                           cwd=proyecto, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    if hecho.returncode != 0:
        sys.exit(f"'{compilador}' no compiló la V1:\n{hecho.stdout[-2000:]}{hecho.stderr[-2000:]}")


def unidades(carpeta: str) -> dict:
    return {os.path.basename(p): open(p, "rb").read()
            for p in sorted(glob.glob(os.path.join(carpeta, "*.phir")))}


def main() -> int:
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--desde-v0", action="store_true",
                      help="arrancar de la V0 en vez de la semilla actual")
    args.add_argument("--vm", default=None, help="el binario suriax-hir")
    opciones = args.parse_args()
    vm = opciones.vm or vm_por_defecto()

    with tempfile.TemporaryDirectory(prefix="suriax-semilla-") as tmp:
        proyecto = os.path.join(tmp, "v1")
        arma_proyecto(proyecto)
        if opciones.desde_v0:
            hecho = subprocess.run([sys.executable, os.path.join(REPO, "V0", "main.py"),
                                    "main.srcx", "--emit-hir"], cwd=proyecto,
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", env={**os.environ, "PYTHONUTF8": "1"})
            if hecho.returncode != 0:
                sys.exit(f"la V0 no compiló la V1:\n{hecho.stdout[-2000:]}{hecho.stderr[-2000:]}")
            origen = os.path.join(proyecto, "dumps", "main.srcx.phir")
        else:
            origen = os.path.join(AQUI, "main.srcx.phir")
            if not os.path.isfile(origen):
                sys.exit("no hay semilla: genera la primera con --desde-v0")
        compila(vm, origen, "etapa1", proyecto)
        compila(vm, os.path.join(proyecto, "etapa1", "main.srcx.phir"), "etapa2", proyecto)
        primera = unidades(os.path.join(proyecto, "etapa1"))
        segunda = unidades(os.path.join(proyecto, "etapa2"))
        if primera != segunda:
            distintas = sorted(n for n in set(primera) | set(segunda)
                               if primera.get(n) != segunda.get(n))
            sys.exit(f"no hay punto fijo: difieren {distintas}. La semilla NO se reemplazó")
        anteriores = unidades(AQUI)
        for vieja in glob.glob(os.path.join(AQUI, "*.phir")):
            os.remove(vieja)
        for nombre, datos in segunda.items():
            with open(os.path.join(AQUI, nombre), "wb") as fh:
                fh.write(datos)
    cambio = "sin cambios" if anteriores == segunda else "actualizada"
    print(f"semilla {cambio}: {len(segunda)} unidades, "
          f"{sum(len(d) for d in segunda.values())} bytes (punto fijo comprobado)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
