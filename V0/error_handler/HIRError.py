from __future__ import annotations

from typing import Any, Optional

try:
    from .error import CompilerError
except ImportError:  # pragma: no cover - compatibility for direct execution
    from error import CompilerError


class HIRError(CompilerError):
    """Base para todos los errores del HIR.

    El HIR es el puente entre el frontend de Python y el backend de C++/LLVM.
    Como está basado en un modelo intermedio y, en esta propuesta, en protobuf,
    los errores deben ser muy explícitos: fallos en la construcción del mensaje,
    conversiones incompatibles, datos faltantes o incompatibilidades de esquema.
    """

    def __init__(
        self,
        message: Any,
        code: str = "HIR000",
        line: Optional[int] = None,
        column: Optional[int] = None,
        file: Optional[str] = None,
        loc: Any = None,
    ):
        super().__init__(
            message,
            code=code,
            line=line,
            column=column,
            file=file,
            phase="hir",
            loc=loc,
        )


class HIRMessageBuildError(HIRError):
    """No fue posible construir un mensaje protobuf para el nodo HIR."""

    def __init__(self, message: Any = "no se pudo construir el mensaje HIR", **kwargs: Any):
        super().__init__(message, code="HIR001", **kwargs)


class HIRFieldMissingError(HIRError):
    """Falta un campo obligatorio en un mensaje HIR o en una instrucción."""

    def __init__(self, message: Any = "falta un campo obligatorio en el HIR", **kwargs: Any):
        super().__init__(message, code="HIR002", **kwargs)


class HIRTypeMismatchError(HIRError):
    """El tipo de una expresión o variable no coincide con lo esperado por el HIR."""

    def __init__(self, message: Any = "tipo incompatible en el HIR", **kwargs: Any):
        super().__init__(message, code="HIR003", **kwargs)


class HIRSchemaMismatchError(HIRError):
    """El mensaje HIR no cumple con el esquema esperado por la versión actual."""

    def __init__(self, message: Any = "incompatibilidad de esquema en el HIR", **kwargs: Any):
        super().__init__(message, code="HIR004", **kwargs)


class HIRUnsupportedInstructionError(HIRError):
    """Se encontró una instrucción o nodo no soportado por el HIR."""

    def __init__(self, message: Any = "instrucción no soportada en el HIR", **kwargs: Any):
        super().__init__(message, code="HIR005", **kwargs)


class HIRConversionError(HIRError):
    """No se pudo convertir un nodo de AST o de Python a una forma válida del HIR."""

    def __init__(self, message: Any = "falló la conversión al HIR", **kwargs: Any):
        super().__init__(message, code="HIR006", **kwargs)


class HIRSerializationError(HIRError):
    """No fue posible serializar o deserializar el mensaje HIR."""

    def __init__(self, message: Any = "falló la serialización del HIR", **kwargs: Any):
        super().__init__(message, code="HIR007", **kwargs)


class HIRSymbolResolutionError(HIRError):
    """Un símbolo, nombre o referencia no pudo resolverse en el HIR."""

    def __init__(self, message: Any = "no se pudo resolver un símbolo en el HIR", **kwargs: Any):
        super().__init__(message, code="HIR008", **kwargs)


class HIRNameCollisionError(HIRError):
    """Dos símbolos o nombres del HIR colisionan en el mismo contexto."""

    def __init__(self, message: Any = "colisión de nombres en el HIR", **kwargs: Any):
        super().__init__(message, code="HIR009", **kwargs)


class HIRInvalidNodeError(HIRError):
    """El nodo o estructura del HIR es inválido o inconsistente."""

    def __init__(self, message: Any = "nodo HIR inválido", **kwargs: Any):
        super().__init__(message, code="HIR010", **kwargs)


__all__ = [
    "HIRError",
    "HIRMessageBuildError",
    "HIRFieldMissingError",
    "HIRTypeMismatchError",
    "HIRSchemaMismatchError",
    "HIRUnsupportedInstructionError",
    "HIRConversionError",
    "HIRSerializationError",
    "HIRSymbolResolutionError",
    "HIRNameCollisionError",
    "HIRInvalidNodeError",
]
