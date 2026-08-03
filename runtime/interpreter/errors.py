"""Errores de RUNTIME del intérprete (``ARQUITECTURA.md`` — módulo ``errors.py``).

Jerarquía propia, separada de ``V0/error_handler`` (esos son errores de
COMPILACIÓN): aquí el programa ya validó estáticamente y falla EJECUTANDO —
la red de la que caen los casos que el análisis conservador no ve
(use-after-move a través de ramas, use-after-free, null deref...).

Cada error lleva código estable ``RTxxx`` y la posición (``ln``/``col``) del
nodo HIR que lo disparó, para el reporte educativo.
"""

from __future__ import annotations

from typing import Optional


class SuriaXRuntimeError(Exception):
    """Base de todos los errores de ejecución del intérprete.

    ``severity`` (ver ``V0/error_handler/error.Severity``): un error de runtime
    corta la ejecución, así que por defecto es ``"critical"``; las violaciones
    de MEMORIA lo suben a ``"panic"`` (la clase más grave — es el error que el
    backend de memoria hace cumplir)."""

    code = "RT000"
    severity = "critical"

    def __init__(self, message: str, *, ln: int = 0, col: int = 0,
                 fn: Optional[str] = None):
        self.message = message
        self.ln = ln
        self.col = col
        self.fn = fn
        where = f" ({fn}:" if fn else " ("
        loc = f"{where}{ln}:{col})" if ln else ""
        super().__init__(f"{self.code}: {message}{loc}")


class UseAfterMoveError(SuriaXRuntimeError):
    """Lectura de una celda cuyo valor fue transferido con ``move``."""
    code = "RT001"
    severity = "panic"


class DoubleMoveError(SuriaXRuntimeError):
    """``move`` sobre una celda ya movida."""
    code = "RT002"
    severity = "panic"


class UseAfterFreeError(SuriaXRuntimeError):
    """Acceso a una celda liberada con ``free`` (o a través de un puntero
    colgante hacia ella)."""
    code = "RT003"
    severity = "panic"


class NullDereferenceError(SuriaXRuntimeError):
    """Desreferencia (acceso a miembro/índice) de un valor ``null``."""
    code = "RT004"
    severity = "panic"


class InvalidFreeError(SuriaXRuntimeError):
    """``free`` sobre un valor que no es un puntero vivo."""
    code = "RT005"
    severity = "panic"


class UndefinedNameError(SuriaXRuntimeError):
    """Nombre no ligado en el environment (defensivo: la Semántica ya lo
    valida; si salta aquí hay una brecha del análisis estático)."""
    code = "RT006"


class NotCallableError(SuriaXRuntimeError):
    """Llamada sobre algo que no es función/hook/intrínseco."""
    code = "RT007"


class MissingIntrinsicError(SuriaXRuntimeError):
    """Un PROTOTIPO (fn sin cuerpo) no tiene intrínseco registrado en el
    host: el HIR es ejecutable solo si el host provee esa primitiva."""
    code = "RT008"


class MissingEntryError(SuriaXRuntimeError):
    """La función de entrada configurada no existe en el módulo principal."""
    code = "RT009"


class StepLimitError(SuriaXRuntimeError):
    """Se alcanzó ``interpreter.max_steps`` (guarda contra bucles infinitos)."""
    code = "RT010"


class UnsupportedNodeError(SuriaXRuntimeError):
    """Nodo HIR sin soporte de ejecución todavía (parte del plan por fases)."""
    code = "RT011"


class InvalidCastRuntimeError(SuriaXRuntimeError):
    """``cast`` sin conversión resoluble en runtime (par no registrado)."""
    code = "RT012"


class IndexOutOfRangeError(SuriaXRuntimeError):
    """``buf[i]`` con ``i`` fuera de ``[0, tamaño)`` (o no entero) sobre un
    bloque reservado con ``__reserve__``."""
    code = "RT013"
    severity = "panic"  # acceso fuera de rango = violacion de memoria


class NotIndexableError(SuriaXRuntimeError):
    """``x[i]`` sobre un valor que no es un bloque reservable ni un puntero
    a uno (la indexación solo opera sobre memoria de ``__reserve__``)."""
    code = "RT014"


class CorruptMemoryHandleError(SuriaXRuntimeError):
    """El backend de memoria recibió un handle INVÁLIDO (``BAD_HANDLE``): una
    celda que no existe. No debería ocurrir con un HIR válido — indica una
    brecha del intérprete o del backend, no un error del programa usuario. Es
    ``panic`` por ser un fallo de integridad de memoria."""
    code = "RT015"
    severity = "panic"


__all__ = [
    "SuriaXRuntimeError", "UseAfterMoveError", "DoubleMoveError",
    "UseAfterFreeError", "NullDereferenceError", "InvalidFreeError",
    "UndefinedNameError", "NotCallableError", "MissingIntrinsicError",
    "MissingEntryError", "StepLimitError", "UnsupportedNodeError",
    "InvalidCastRuntimeError", "IndexOutOfRangeError", "NotIndexableError",
    "CorruptMemoryHandleError",
]
