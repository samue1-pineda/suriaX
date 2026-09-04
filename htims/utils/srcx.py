"""La línea ``hook fn`` que hay que escribir en el ``.srcx``.

El otro lado de :mod:`htims.utils.cxx`. De una misma declaración salen dos
contratos: el prototipo C++ que ``logic_dir`` implementará (si es
``cxx=True``) y la línea de suriaX que el programa tiene que escribir para
implementar el hook. Los dos se generan desde la firma declarada, así que no
hay que copiarla a mano a ningún sitio — copiarla es exactamente donde
aparecen los desajustes que luego reporta la Semántica.

    python -m htims.utils.srcx extensions/calls/
"""

from __future__ import annotations

import sys
from typing import List, Sequence

from ..declarations import HookDecl


def stub(decl: HookDecl) -> str:
    """La declaración en suriaX de un hook, con nombres de parámetro.

    El primer parámetro se llama ``self`` cuando su tipo es el del dueño: es
    el receptor, y así se escribe en el resto del lenguaje (``@impl``).
    """
    nombres: List[str] = []
    for indice, tipo in enumerate(decl.params):
        base = tipo.split(" ")[0]
        if indice == 0 and base == decl.owner:
            nombres.append(f"{tipo} self")
        else:
            nombres.append(f"{tipo} arg{indice + 1}")
    firma = ", ".join(nombres)
    return f"hook fn {decl.name}({firma}) -> {decl.returns} {{ }}"


def stubs(decls: Sequence[HookDecl]) -> str:
    """Las declaraciones de todos, agrupadas por dueño."""
    lineas: List[str] = []
    dueno = None
    for decl in sorted(decls, key=lambda d: (d.owner, d.name)):
        if decl.owner != dueno:
            dueno = decl.owner
            lineas.append(f"\n// hooks de '{dueno}'")
        origen = f"{decl.module}.py:{decl.line}"
        destino = f" [logic: {decl.logic}]" if decl.cxx else ""
        lineas.append(f"// declarado en {origen}{destino}")
        lineas.append(stub(decl))
    return "\n".join(lineas).lstrip("\n")


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m htims.utils.srcx <ruta>...`` -> los stubs por stdout."""
    from .check import check

    rutas = list(argv if argv is not None else sys.argv[1:])
    if not rutas:
        print("uso: python -m htims.utils.srcx <ruta>...", file=sys.stderr)
        return 2
    decls, errores = check(*rutas)
    for problema in errores:
        print(f"{problema.code} {problema.loc.strformat()} {problema.message}",
              file=sys.stderr)
    if errores:
        return 1
    print(stubs(decls))
    return 0


if __name__ == "__main__":  # pragma: no cover - entrada de la CLI
    raise SystemExit(main())


__all__ = ["stub", "stubs", "main"]
