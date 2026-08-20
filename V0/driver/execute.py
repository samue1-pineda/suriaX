"""Entrega del ``.phir`` al intérprete, y cierre del reporte de depuración.

Compilar y ejecutar son dos cosas, y estaban en la misma función. Separarlas
es lo que permite que ``suri run`` decida por su cuenta —compilar sin
ejecutar, ejecutar un ``.phir`` ya compilado, o compilar y ejecutar con otro
runtime— sin tocar el pipeline.

El reporte de ``--debug`` se cierra AQUÍ y no en el pipeline por una razón
concreta: incluye la traza de ejecución, que todavía no existe cuando la
compilación termina.
"""

from __future__ import annotations

import time
from typing import Optional

from .options import EXIT_MISSING_DEPENDENCY, CompileResult
from .reporting import Reporter, SilentReporter


def execute(result: CompileResult, *,
            trace_exec: bool = False, trace_memory: bool = False,
            reporter: Optional[Reporter] = None) -> int:
    """Ejecuta el ``.phir`` de ``result`` EN PROCESO y devuelve su código.

    En proceso —sin subproceso ni reparseo— porque el HIR ya está en memoria
    del lado del compilador y volver a leerlo solo añadiría latencia. Con
    ``--debug`` la traza se ACUMULA en ``result.trace_events`` para el reporte
    en vez de imprimirse.
    """
    reporter = reporter or SilentReporter()
    if not result.should_run or result.phir_path is None:
        return result.status

    t = time.perf_counter()
    from runtime.interpreter import interpreter as interp
    from runtime.interpreter import loader as interp_loader

    icfg = dict(result.config.get("interpreter") or {})
    icfg.setdefault("entry", "main")
    if trace_memory:
        icfg["trace_memory"] = True
    if trace_exec:
        icfg["trace_exec"] = True
    exit_code = result.status
    try:
        image = interp_loader.load_image(result.phir_path)
        exit_code = interp.run(image, {"interpreter": icfg},
                               events=result.trace_events)
    except interp_loader.HIRLoadError as exc:
        reporter.warn(f"error cargando HIR: {exc}")
        exit_code = EXIT_MISSING_DEPENDENCY
    result.times["interprete"] = time.perf_counter() - t
    result.status = exit_code
    return exit_code


def finish_report(result: CompileResult) -> Optional[str]:
    """Cierra el reporte de ``--debug`` (traza + tiempos) y lo escribe.

    Devuelve la ruta escrita, o ``None`` si no se pidió el reporte.
    """
    report = result.debug_report
    if report is None:
        return None
    report.diagnostics("ERRORES LEXICOS", result.lexer_errors)
    report.trace(result.trace_events)
    report.timings(result.times)
    result.report_file = report.write()
    return result.report_file


__all__ = ["execute", "finish_report"]
