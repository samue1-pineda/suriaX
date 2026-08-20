"""Cómo se ve el compilador en una terminal.

Todo lo que el driver *cuenta* pasa por aquí, y solo por aquí. La regla que
justifica el módulo: los **hechos** van a ``stdout`` (lo que produjo la
compilación, lo que un script querría capturar) y los **diagnósticos** a
``stderr`` (lo que se lee mientras se arregla algo). Estaba repartido en
veinte ``print`` dentro del pipeline, así que cambiar el formato obligaba a
tocar el compilador.
"""

from __future__ import annotations

import sys
import time
from typing import List

from driver import CompileResult


class TerminalReporter:
    """El :class:`~driver.reporting.Reporter` de la línea de comandos."""

    def info(self, message: str) -> None:
        print(message)

    def warn(self, message: str) -> None:
        print(message, file=sys.stderr)

    def diagnostics(self, title: str, errors: List) -> None:
        print(f"\n=== {title} ({len(errors)}) ===", file=sys.stderr)
        for err in errors:
            sev = getattr(err, "severity", "critical")
            print(f"  [{sev}] {err.code}: {err.message}  ({err.loc})",
                  file=sys.stderr)


def print_result(result: CompileResult) -> None:
    """Lo que se imprime DESPUÉS de compilar: log, tiempos y reporte.

    Va aparte del reporter porque no es progreso: son cierres que solo tienen
    sentido cuando la compilación ya terminó.
    """
    if result.log_file:
        print(f"(diagnosticos registrados en {result.log_file})",
              file=sys.stderr)


def print_times(result: CompileResult) -> None:
    """Tiempos por fase (``--time``). Incluye la ejecución si la hubo, y por
    eso se imprime al final y no dentro del pipeline.

    El TOTAL es el RELOJ DE PARED del proceso, no la suma de las fases. La
    diferencia entre ambos —el arranque del intérprete de Python y la
    importación del compilador, que ocurren antes de que exista una fase que
    cronometrar— se reporta como ``arranque`` en vez de desaparecer: sumando
    solo las fases, el TOTAL daba como un tercio del tiempo real, que es
    justo el número equivocado para quien mide para saber por qué tarda.
    """
    filas = list(result.times.items())
    fases = sum(secs for _n, secs in filas)
    reloj = _reloj_de_pared()
    if reloj is not None and reloj > fases:
        # todo lo que no cae dentro de una fase medida: arranque del proceso,
        # importacion del compilador y el pegamento entre fases.
        filas.insert(0, ("arranque", reloj - fases))
    total = reloj if reloj is not None else fases
    print("\n=== tiempos por fase ===", file=sys.stderr)
    for name, secs in filas:
        print(f"  {name:<14} {secs * 1000:8.2f} ms", file=sys.stderr)
    print(f"  {'TOTAL':<14} {total * 1000:8.2f} ms", file=sys.stderr)


def _reloj_de_pared():
    """Segundos desde que arrancó el proceso, o ``None`` si no se sabe.

    ``V0/main.py`` estampa ``ARRANQUE`` en su primera línea ejecutable. Se
    consulta por ``sys.modules`` y no con un import porque el compilador
    también se usa como LIBRERÍA (``driver``): ahí no hay un ``main`` que haya
    estampado nada, y entonces se reporta solo la suma de las fases.
    """
    inicio = getattr(sys.modules.get("__main__"), "ARRANQUE", None)
    if inicio is None:
        return None
    return time.perf_counter() - inicio


def print_file_not_found(path: str) -> None:
    print(f"archivo no encontrado: {path}", file=sys.stderr)


__all__ = ["TerminalReporter", "print_result", "print_times",
           "print_file_not_found"]
