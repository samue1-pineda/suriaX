"""El contrato de entrada y salida del driver.

Antes, compilar era una función con doce parámetros por palabra clave y un
``int`` de retorno: el llamador tenía que saber el orden del pipeline para
interpretarlo, y todo lo que la compilación había averiguado —métricas,
artefactos escritos, tiempos por fase— se perdía por stdout sin que nadie
pudiera consultarlo.

:class:`CompileOptions` agrupa el *qué se pide* y :class:`CompileResult` el
*qué salió*. El código de salida deja de ser el canal de información y pasa a
DERIVARSE del resultado (:meth:`CompileResult.exit_code`), que es lo que
permite a otro front —``suri run``— tomar sus propias decisiones sin
reimplementar la tabla de códigos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

#: códigos de salida del compilador (ver FLAGS.md secc. 6).
EXIT_OK = 0
EXIT_COMPILE_ERROR = 1
EXIT_FILE_NOT_FOUND = 2
EXIT_MISSING_DEPENDENCY = 3
EXIT_EXTENSION_ERROR = 4
EXIT_CONFIG_ERROR = 5
#: el COMPILADOR falló (ICE000): un bug suyo, no del programa. Distinto de 1
#: para que un script, la CI o el LSP no lean "tu programa tiene errores".
EXIT_INTERNAL_ERROR = 6


@dataclass
class CompileOptions:
    """Qué se le pide a una compilación.

    Los ``Optional[str]`` de volcado siguen la convención del argparse que los
    origina: ``None`` = no se pidió, ``""`` = se pidió a la ruta por defecto,
    y una cadena = esa ruta. Se conserva porque distingue tres estados que un
    ``bool`` no puede.
    """
    emit_ast_json: Optional[str] = None
    emit_tokens: Optional[str] = None
    emit_hir: Optional[str] = None
    hir_pretty: Optional[str] = None
    dump_symbols: Optional[str] = None
    hir_text: bool = False
    #: ejecutar: None = no (salvo que el target lo pida), "" = en el motor del
    #: yaml, "compiler" / "interpreter" = ese. 'True' vale como "".
    run: Optional[object] = None
    debug: bool = False
    collect_times: bool = False
    trace_exec: bool = False
    trace_memory: bool = False


@dataclass
class CompileResult:
    """Qué salió de una compilación.

    ``status`` es el motivo por el que se paró (o ``EXIT_OK``); ``phir_path``
    solo está si el HIR se emitió limpio, que es la precondición para
    ejecutar. ``should_run`` la calcula el driver a partir del target y de las
    opciones, pero EJECUTAR es decisión del llamador: el pipeline compila.
    """
    path: str
    status: int = EXIT_OK
    config: Dict[str, Any] = field(default_factory=dict)
    phir_path: Optional[str] = None
    should_run: bool = False
    #: en que motor se ejecuta: "compiler" (la VM) o "interpreter"
    motor: str = "interpreter"
    times: Dict[str, float] = field(default_factory=dict)
    metrics: Dict[str, int] = field(default_factory=dict)
    artifacts: Dict[str, str] = field(default_factory=dict)
    diagnostics: List = field(default_factory=list)
    notes: List = field(default_factory=list)
    log_file: Optional[str] = None
    report_file: Optional[str] = None
    trace_events: Optional[List] = None
    #: reporte de --debug a medio construir: le falta la traza, que solo
    #: existe DESPUES de ejecutar. Lo cierra 'driver.execute.finish_report'.
    debug_report: Any = None
    #: los lexicos aparte de 'diagnostics' porque el reporte de depuracion los
    #: agrupa por fase y necesita distinguirlos del resto.
    lexer_errors: List = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == EXIT_OK

    def exit_code(self) -> int:
        """El código con el que terminaría un proceso que hiciera esto."""
        return self.status


__all__ = [
    "CompileOptions", "CompileResult",
    "EXIT_OK", "EXIT_COMPILE_ERROR", "EXIT_FILE_NOT_FOUND",
    "EXIT_MISSING_DEPENDENCY", "EXIT_EXTENSION_ERROR", "EXIT_CONFIG_ERROR",
    "EXIT_INTERNAL_ERROR",
]
