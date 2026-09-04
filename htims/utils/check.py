"""Verificar tus declaraciones sin compilar un ``.srcx``.

Un error en una declaración detiene la compilación entera (todo ``EXT0xx`` es
crítico), así que descubrirlo al compilar el proyecto es tarde y caro. Esto
corre **el mismo escaneo** que usa el compilador —``declarations.scan_files``,
sin importar ni ejecutar tu archivo— y devuelve lo que diría.

Que sea el mismo escaneo es el punto: una verificación propia sería una
segunda respuesta a la misma pregunta, y acabaría discrepando del compilador
justo cuando más importa.

    python -m htims.utils.check extensions/calls/
"""

from __future__ import annotations

import os
import sys
from typing import Iterable, List, Sequence

from ..declarations import HookDecl, scan_files
from ..errors import ExtensionError


def archivos(*rutas: str) -> List[str]:
    """Los ``.py`` de las rutas dadas (un archivo se toma tal cual).

    Ignora los privados (``_x.py``) y ``__pycache__``, igual que el
    descubrimiento del compilador: si el compilador no los va a escanear,
    verificarlos aquí daría una respuesta que no se corresponde.
    """
    salida: List[str] = []
    for ruta in rutas:
        if os.path.isfile(ruta):
            salida.append(ruta)
            continue
        for base, dirs, nombres in os.walk(ruta):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for nombre in sorted(nombres):
                if nombre.endswith(".py") and not nombre.startswith("_"):
                    salida.append(os.path.join(base, nombre))
    return salida


def check(*rutas: str) -> tuple[List[HookDecl], List[ExtensionError]]:
    """Escanea y devuelve ``(declaraciones, errores)``.

    Nunca lanza: los problemas son el valor de retorno, mismo contrato que
    el resto del compilador.
    """
    _proyecto, decls, errores = scan_files(archivos(*rutas))
    return decls, errores


def report(decls: Sequence[HookDecl], errores: Iterable[ExtensionError]) -> str:
    """Las dos listas como texto para una terminal."""
    lineas: List[str] = []
    for decl in decls:
        destino = f"  -> {decl.logic} (C++)" if decl.cxx else ""
        firma = ", ".join(decl.params)
        lineas.append(f"  {decl.owner}.{decl.name}({firma}) -> "
                      f"{decl.returns}{destino}")
    fallos = list(errores)
    for problema in fallos:
        lineas.append(f"  {problema.code} {problema.loc.strformat()} "
                      f"{problema.message}")
    if not lineas:
        lineas.append("  (ninguna declaración encontrada)")
    resumen = f"{len(decls)} declaración(es), {len(fallos)} error(es)"
    return "\n".join(lineas + ["", resumen])


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m htims.utils.check <ruta>...``; ``1`` si hay errores."""
    rutas = list(argv if argv is not None else sys.argv[1:])
    if not rutas:
        print(__doc__.strip().splitlines()[-1].strip())
        return 2
    decls, errores = check(*rutas)
    print(report(decls, errores))
    return 1 if errores else 0


if __name__ == "__main__":  # pragma: no cover - entrada de la CLI
    raise SystemExit(main())


__all__ = ["archivos", "check", "report", "main"]
