"""El compilador suriaX como **librería**: compilar sin pasar por la terminal.

Esta es la frontera que separa *qué hace el compilador* de *cómo se pide y
cómo se muestra*. Todo lo que hay aquí funciona sin ``argparse``, sin
``stdout`` y sin códigos de salida como canal de información:

    from driver import CompileOptions, compile_source, execute

    resultado = compile_source("programa.srcx", CompileOptions(run=True))
    if resultado.should_run:
        execute(resultado)

Existe por suriniX: cuando ``suri run`` sea el punto de entrada, tiene que
poder reutilizar el pipeline entero —no invocar al proceso ni reimplementarlo—
y decidir por su cuenta qué imprime y qué devuelve. La CLI actual
(:mod:`cli`) es solo el primer consumidor de esta API, no su dueña.

    driver/options.py    qué se pide (CompileOptions) y qué sale (CompileResult)
    driver/reporting.py  la costura hacia el llamador (Reporter)
    driver/pipeline.py   compilar: config -> HTIMS -> lexer -> ... -> HIR
    driver/execute.py    ejecutar el .phir e cerrar el reporte de --debug
    driver/inspect.py    canales de consulta del editor (fases, diagnósticos)
"""

from __future__ import annotations

import sys

#: Las pasadas del compilador recorren el arbol de forma recursiva. El parser
#: acota cuanto anida un programa (``MAX_NESTING``), y esto es el margen para
#: recorrerlo: el limite de Python por defecto (1000) no alcanza para las
#: pasadas que gastan varios marcos por nivel. Va AQUI y no solo en la CLI
#: para que quien usa el compilador como libreria —el playground, el editor—
#: tenga el mismo que ``V0/main.py``; antes una suma de 300 terminos
#: compilaba en la terminal y era un fallo interno en el playground.
RECURSION_LIMIT = 10_000
if sys.getrecursionlimit() < RECURSION_LIMIT:
    sys.setrecursionlimit(RECURSION_LIMIT)

from .execute import execute, finish_report  # noqa: E402
from .options import (EXIT_COMPILE_ERROR, EXIT_CONFIG_ERROR,
                      EXIT_EXTENSION_ERROR, EXIT_FILE_NOT_FOUND,
                      EXIT_INTERNAL_ERROR, EXIT_MISSING_DEPENDENCY, EXIT_OK,
                      CompileOptions, CompileResult)
from .pipeline import compile_source, emit_library_units, load_config
from .reporting import Reporter, SilentReporter

__all__ = [
    "CompileOptions", "CompileResult", "Reporter", "SilentReporter",
    "compile_source", "emit_library_units", "execute", "finish_report",
    "load_config",
    "EXIT_OK", "EXIT_COMPILE_ERROR", "EXIT_FILE_NOT_FOUND",
    "EXIT_MISSING_DEPENDENCY", "EXIT_EXTENSION_ERROR", "EXIT_CONFIG_ERROR",
    "EXIT_INTERNAL_ERROR",
]
