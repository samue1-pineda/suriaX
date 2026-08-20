"""Diagnósticos del formato de compilación — familia ``CFG0xx``.

**Por qué esta clase no hereda de ``V0/error_handler``.** El paquete
``config/`` es transversal y NO forma parte del frontend: importar
``error_handler`` lo ataría a ``V0/``, la frontera que este paquete respeta
(mismo razonamiento que ``htims/errors.py``). En vez de heredar,
:class:`ConfigError` reproduce el CONTRATO que el resto del compilador ya
consume —``.code``, ``.message``, ``.line``, ``.column``, ``.file``,
``.phase``, ``.severity``, ``.loc.strformat()`` y ``.to_dict()``— así que el
impresor de errores, el log JSONL y el canal ``--emit-diagnostics`` lo tratan
igual que a un ``LexError`` o a un ``ExtensionError``.

**Por qué existe.** Hasta ahora un ``.suriaX_config.yaml`` mal escrito se
descartaba EN SILENCIO: un yaml roto, un ``target`` inventado, una clave con
una letra de más (``libsrx_path`` por ``libsrx_paths``) o un valor del tipo
equivocado se ignoraban y la compilación seguía con los valores por defecto.
El usuario veía el síntoma mucho después y en otro sitio —"no se encontró la
librería X"— sin ninguna pista de que su configuración nunca se aplicó.

Casi toda la familia es CRÍTICA: una configuración que dice algo distinto de
lo que su autor cree es peor que no tenerla, y seguir compilando contra unos
ajustes que ya se rechazaron solo mueve el síntoma de sitio.

La excepción es ``CFG007`` (falta ``pyyaml``), que es una ADVERTENCIA: el
frontend completo corre con la librería estándar —es un contrato del proyecto,
ver ``how_to_run.md``— así que no tener el lector de yaml no puede impedir
compilar. Lo que sí hace es avisar bien fuerte, porque el usuario cree que su
configuración se está aplicando y no es así.
"""

from __future__ import annotations

from typing import Any, Optional

#: fase que se reporta en los diagnósticos (el canal del LSP agrupa por ella).
PHASE = "config"

# --------------------------------------------------------------------------- #
# catálogo de códigos — un código = una causa, sin solapamiento
# --------------------------------------------------------------------------- #
CFG001 = "CFG001"  # el archivo existe pero no se pudo leer (I/O, no UTF-8)
CFG002 = "CFG002"  # YAML malformado (error de sintaxis del parser)
CFG003 = "CFG003"  # la raíz del documento no es un mapa clave/valor
CFG004 = "CFG004"  # clave desconocida (típicamente un typo)
CFG005 = "CFG005"  # el valor no es del tipo que la clave espera
CFG006 = "CFG006"  # el valor no está entre los admitidos por esa clave
CFG007 = "CFG007"  # hay un yaml en disco pero falta pyyaml para leerlo


class Location:
    """Ubicación de un diagnóstico. Espejo mínimo de
    ``error_handler.error.SourceLocation`` (mismo ``strformat``), sin heredar
    de él para no cruzar la frontera con ``V0/``."""

    __slots__ = ("line", "column", "file")

    def __init__(self, line: int = 1, column: int = 1, file: Optional[str] = None):
        self.line = line
        self.column = column
        self.file = file

    def strformat(self) -> str:
        if self.file:
            return f"{self.file}:{self.line}:{self.column}"
        return f"line {self.line}, column {self.column}"

    def __str__(self) -> str:
        return self.strformat()


class ConfigError(Exception):
    """Diagnóstico del formato de compilación.

    Es una excepción por conveniencia, pero el flujo normal la ACUMULA y la
    reporta en bloque: un yaml con tres claves mal escritas las muestra las
    tres, no la primera. Mismo contrato que el resto del compilador.
    """

    #: severidad POR DEFECTO de la familia; una instancia puede bajarla
    #: (CFG007 es una advertencia, no un error).
    DEFAULT_SEVERITY = "critical"
    phase: str = PHASE

    __slots__ = ("code", "message", "line", "column", "file", "loc",
                 "severity")

    def __init__(self, code: str, message: str, *, file: Optional[str] = None,
                 line: int = 1, column: int = 1,
                 severity: Optional[str] = None):
        # la severidad es por INSTANCIA porque una sola de la familia no es
        # critica (CFG007); el resto hereda la de la clase.
        self.severity = severity or self.DEFAULT_SEVERITY
        self.code = code
        self.message = message
        self.line = line
        self.column = column
        self.file = file
        self.loc = Location(line=line, column=column, file=file)
        super().__init__(f"{message}\n{self.loc}")

    def to_dict(self) -> dict[str, Any]:
        """Forma serializable — MISMAS claves que ``CompilerError.to_dict()``."""
        return {
            "code": self.code,
            "message": self.message,
            "line": self.line,
            "column": self.column,
            "file": self.file,
            "phase": self.phase,
            "severity": self.severity,
            "location": self.loc.strformat(),
        }

    def __str__(self) -> str:
        return self.args[0] if self.args else self.message

    def __repr__(self) -> str:  # pragma: no cover - ayuda al depurar tests
        return f"<ConfigError {self.code} {self.loc.strformat()}>"


__all__ = ["PHASE", "Location", "ConfigError",
           "CFG001", "CFG002", "CFG003", "CFG004", "CFG005", "CFG006", "CFG007"]
