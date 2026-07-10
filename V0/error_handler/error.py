from __future__ import annotations
from typing import Optional, Any


class SourceLocation:
    """Representa la ubicación de un problema en el código fuente.

    Se usa para guardar información de archivo, línea y columna de forma
    simple y reutilizable. Es la pieza base para mostrar mensajes más claros
    en lexer, parser, semántica y backend.
    """

    def __init__(self, line: int = 1, column: int = 1, file: Optional[str] = None):
        self.line = line
        self.column = column
        self.file = file

    def strformat(self) -> str:
        """Devuelve una cadena legible para mostrar la ubicación."""
        if self.file:
            return f"{self.file}:{self.line}:{self.column}"
        return f"line {self.line}, column {self.column}"

    def __str__(self) -> str:
        return self.strformat()


class SuriWarning(Warning):
    """Advertencia del compilador.

    No detiene la compilación, pero permite reportar problemas como tokens
    sospechosos, escapes raros o construcciones ambiguas.
    """

    def __init__(self, msg: Any, loc: Any = None, highlightig: bool = True):
        self.msg = str(msg) if msg is not None else ""
        self.loc = self._coerce_location(loc)
        self.highlightig = highlightig
        super().__init__(self._build_message(self.msg, self.loc))

    @staticmethod
    def _coerce_location(loc: Any) -> Optional[SourceLocation]:
        """Convierte distintas formas de ubicación a un SourceLocation."""
        if loc is None:
            return None
        if isinstance(loc, SourceLocation):
            return loc
        if isinstance(loc, (list, tuple)) and len(loc) == 2:
            line, column = loc
            return SourceLocation(line=line, column=column)
        if hasattr(loc, "strformat"):
            return loc
        return SourceLocation(line=1, column=1, file=str(loc))

    @staticmethod
    def _build_message(msg: str, loc: Optional[SourceLocation]) -> str:
        """Compone el mensaje final mostrando el texto y la ubicación."""
        if loc is None:
            return msg
        return f"{msg}\n{loc}"

    def __str__(self) -> str:
        return self.args[0] if self.args else self.msg


class CompilerError(Exception):
    """Error base del compilador.

    Esta clase sirve como plantilla para todos los errores del proyecto.
    Permite:
    - guardar un código estable para serialización,
    - conservar ubicación del problema,
    - formatear mensajes legibles,
    - exponerse a logs, tests o JSON.
    """

    def __init__(
        self,
        message: Any,
        code: str = "ERR000",
        line: Optional[int] = None,
        column: Optional[int] = None,
        file: Optional[str] = None,
        phase: Optional[str] = None,
        loc: Any = None,
    ):
        # Información básica del error.
        self.code = code
        self.message = str(message) if message is not None else ""
        self.line = line
        self.column = column
        self.file = file
        self.phase = phase

        # Ubicación del problema, ya sea como objeto o como datos simples.
        self.loc = self._coerce_location(loc, line=line, column=column, file=file)

        # El mensaje que se mostrará al usuario o al depurador.
        super().__init__(self._build_message(self.message, self.loc))

    @staticmethod
    def _coerce_location(
        loc: Any,
        line: Optional[int],
        column: Optional[int],
        file: Optional[str],
    ) -> Optional[SourceLocation]:
        """Convierte distintos tipos de ubicación a SourceLocation."""
        if loc is None:
            if line is None and column is None and file is None:
                return None
            return SourceLocation(line=line or 1, column=column or 1, file=file)
        if isinstance(loc, SourceLocation):
            return loc
        if isinstance(loc, (list, tuple)) and len(loc) == 2:
            line, column = loc
            return SourceLocation(line=line, column=column, file=file)
        if hasattr(loc, "strformat"):
            return loc
        return SourceLocation(line=line or 1, column=column or 1, file=file)

    @staticmethod
    def _build_message(msg: str, loc: Optional[SourceLocation]) -> str:
        """Genera el texto final del error con o sin ubicación."""
        if loc is None:
            return msg
        return f"{msg}\n{loc}"

    def to_dict(self) -> dict[str, Any]:
        """Devuelve una forma serializable del error para logs, JSON o tests."""
        return {
            "code": self.code,
            "message": self.message,
            "line": self.line,
            "column": self.column,
            "file": self.file,
            "phase": self.phase,
            "location": self.loc.strformat() if self.loc else None,
        }

    def __str__(self) -> str:
        return self.args[0] if self.args else self.message

