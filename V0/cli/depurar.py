"""Las banderas de la terminal, para una sesión de depuración.

El depurador (``runtime/interpreter/dap.py``) es del compilador y no conoce a
la CLI; pero quien depura quiere escribir las banderas como en la terminal
(``"flags": ["--test"]`` en la configuración del editor). Este módulo es el
puente, del lado que SÍ puede conocer a los dos: lee las banderas con el
analizador de la terminal y le dice al depurador qué pedir al compilar y qué
al ejecutar. ``--dap`` se lo entrega al arrancar.
"""

from __future__ import annotations

import contextlib
import io
from typing import Dict, List

from .args import build_parser

#: banderas que tienen sentido al depurar, por el nombre de su opción: las que
#: piden un volcado (se compila igual) y las que cambian cómo se ejecuta. El
#: resto —las que no compilan un programa, o lo mandan a la VM, que no se
#: puede depurar— se rechazan diciendo por qué.
_AL_COMPILAR = ("emit_ast_json", "emit_tokens", "emit_hir", "hir_pretty",
                "dump_symbols", "hir_text")
_AL_EJECUTAR = {"trace_exec": "trace_exec", "trace_memory": "trace_memory",
                "pruebas": "pruebas"}


def banderas(programa: str, escritas: List[str]) -> Dict[str, dict]:
    """Las banderas escritas, leídas con el MISMO analizador que la terminal:
    se escriben igual y significan lo mismo. Devuelve
    ``{"compilar": {...}, "ejecutar": {...}}``: los argumentos de
    ``CompileOptions`` y los de ``driver.execute``.

    Lanza ``ValueError`` con un mensaje para quien escribió la configuración.
    """
    escritas = [str(b) for b in escritas]
    parser = build_parser()
    vacio = parser.parse_args([programa])
    dicho = io.StringIO()
    try:
        with contextlib.redirect_stderr(dicho), contextlib.redirect_stdout(dicho):
            pedido = parser.parse_args([programa, *escritas])
    except SystemExit:
        motivo = (dicho.getvalue().strip().splitlines() or ["?"])[-1]
        raise ValueError(f"banderas no válidas en 'flags': {motivo}") from None
    if pedido.source != programa:
        raise ValueError("'flags' no puede nombrar otro programa: el que se "
                         "depura es 'program'")

    compilar, ejecutar, sobran = {}, {}, []
    for nombre, valor in vars(pedido).items():
        if nombre == "source" or valor == getattr(vacio, nombre, None):
            continue
        if nombre in _AL_COMPILAR:
            compilar[nombre] = valor
        elif nombre in _AL_EJECUTAR:
            ejecutar[_AL_EJECUTAR[nombre]] = valor
        else:
            sobran.append("--" + nombre.replace("_", "-"))
    if sobran:
        raise ValueError(
            f"{', '.join(sorted(sobran))}: esa bandera no se puede usar al "
            "depurar (no compila y ejecuta un programa en el intérprete). "
            "Valen las que piden un volcado (--emit-hir, --hir-pretty, "
            "--emit-ast-json, --emit-tokens, --dump-symbols-table, --hir-text) "
            "y --test, --trace-exec y --trace-memory")
    return {"compilar": compilar, "ejecutar": ejecutar}


__all__ = ["banderas"]
