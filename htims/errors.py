"""Diagnósticos de la capa HTIMS — familia ``EXT0xx``.

**Por qué esta clase no hereda de ``V0/error_handler``.** El HTIMS corre
ANTES del léxico y no forma parte del frontend: si importara
``error_handler`` quedaría atado al paquete ``V0/``, justo la frontera que
este módulo existe para respetar (ver ``readme.md``). En vez de heredar,
:class:`ExtensionError` reproduce el CONTRATO que el resto del compilador ya
consume — ``.code``, ``.message``, ``.line``, ``.column``, ``.file``,
``.phase``, ``.severity``, ``.loc.strformat()`` y ``.to_dict()`` — de modo
que el reporter de la CLI (``cli/report.py``), ``CompilerLog.error_batch`` y el canal
``--emit-diagnostics`` lo tratan exactamente igual que a un ``LexError``.
Un cambio en la jerarquía del frontend no rompe este módulo, y viceversa.

Toda la familia es CRÍTICA: un manifiesto malformado o un directorio que no
existe es un proyecto mal configurado, no una advertencia que se pueda
arrastrar (decisión de diseño; ver ``readme.md`` secc. "Severidad").
"""

from __future__ import annotations

from typing import Any, Optional

#: fase que se reporta en los diagnósticos (el canal del LSP agrupa por ella).
PHASE = "extensions"

# --------------------------------------------------------------------------- #
# catálogo de códigos — un código = una causa, sin solapamiento
# --------------------------------------------------------------------------- #
#: manifiesto: forma del archivo
EXT001 = "EXT001"  # el manifiesto existe pero no se pudo leer (I/O, no UTF-8)
EXT002 = "EXT002"  # línea malformada (no es 'clave: valor' ni comentario)
EXT003 = "EXT003"  # un directorio declarado no existe
EXT004 = "EXT004"  # clave desconocida
EXT005 = "EXT005"  # clave duplicada
EXT006 = "EXT006"  # valor vacío
EXT007 = "EXT007"  # falta una clave obligatoria

#: entradas de extensión (los .py declarados)
EXT010 = "EXT010"  # el .py no existe / no se puede leer
EXT011 = "EXT011"  # el .py no es Python válido (SyntaxError)
EXT012 = "EXT012"  # el nombre de proyecto se declara dos veces con valores distintos

#: declaraciones de hook dentro de un .py
EXT020 = "EXT020"  # el nombre no tiene la forma '__x__'
EXT021 = "EXT021"  # falta 'owner' o no es un identificador válido
EXT022 = "EXT022"  # falta 'returns'
EXT023 = "EXT023"  # 'params' no es una lista de cadenas
EXT024 = "EXT024"  # (owner, nombre) declarado dos veces
EXT025 = "EXT025"  # argumento no literal (el escaneo NO ejecuta código)
EXT026 = "EXT026"  # argumento desconocido en el decorador
EXT027 = "EXT027"  # colisión con el vocabulario fijo del compilador
EXT028 = "EXT028"  # C++ pedido desde una firma PURA (negado por defecto)
EXT029 = "EXT029"  # contrato con C++ incompleto o sin declarar explícitamente


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

    def __str__(self) -> str:  # lo que imprime el reporter de la CLI
        return self.strformat()


class ExtensionError(Exception):
    """Diagnóstico de la capa de extensiones.

    Es una excepción por conveniencia (permite un ``raise`` puntual), pero el
    flujo normal la ACUMULA en una lista y la reporta en bloque: un manifiesto
    con tres errores los muestra los tres, no el primero.
    """

    severity: str = "critical"
    phase: str = PHASE

    __slots__ = ("code", "message", "line", "column", "file", "loc")

    def __init__(self, code: str, message: str, *, file: Optional[str] = None,
                 line: int = 1, column: int = 1):
        self.code = code
        self.message = message
        self.line = line
        self.column = column
        self.file = file
        self.loc = Location(line=line, column=column, file=file)
        super().__init__(f"{message}\n{self.loc}")

    def to_dict(self) -> dict[str, Any]:
        """Forma serializable — MISMAS claves que ``CompilerError.to_dict()``
        (logs JSONL, canal ``--emit-diagnostics``, tests)."""
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
        return f"<ExtensionError {self.code} {self.loc.strformat()}>"


__all__ = ["PHASE", "Location", "ExtensionError"]
