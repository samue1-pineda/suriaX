from __future__ import annotations

from typing import Any, Optional

try:
    from .error import CompilerError
except ImportError:  # pragma: no cover - compatibility for direct execution
    from error import CompilerError


class ASTError(CompilerError):
    """Base para los errores relacionados con la construcción y validación del AST."""

    def __init__(
        self,
        message: Any,
        code: str = "AST000",
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
            phase="ast",
            loc=loc,
        )


class InvalidASTNodeError(ASTError):
    """El nodo AST es inconsistente o no corresponde al contexto esperado."""

    def __init__(self, message: Any = "nodo AST inválido", **kwargs: Any):
        super().__init__(message, code="AST001", **kwargs)


class MissingASTNodeError(ASTError):
    """Falta un nodo obligatorio que debería haber sido creado por el parser."""

    def __init__(self, message: Any = "nodo AST faltante", **kwargs: Any):
        super().__init__(message, code="AST002", **kwargs)


class UnexpectedASTStructureError(ASTError):
    """La estructura del AST no encaja con la forma esperada."""

    def __init__(self, message: Any = "estructura AST inesperada", **kwargs: Any):
        super().__init__(message, code="AST003", **kwargs)


class ASTConstructionError(ASTError):
    """No pudo construirse el AST completo o parcialmente."""

    def __init__(self, message: Any = "falló la construcción del AST", **kwargs: Any):
        super().__init__(message, code="AST004", **kwargs)


class UnknownTypeError(ASTError):
    """Se refiere a un tipo que no está definido en el contexto del AST."""

    def __init__(self, message: Any = "tipo no definido", **kwargs: Any):
        super().__init__(message, code="AST005", **kwargs)


class TypeMismatchError(ASTError):
    """El AST contiene una incompatibilidad de tipos."""

    def __init__(self, message: Any = "tipo incompatible", **kwargs: Any):
        super().__init__(message, code="AST006", **kwargs)


class CannotInferTypeError(ASTError):
    """No se puede inferir el tipo de una expresión o nodo."""

    def __init__(self, message: Any = "no se puede inferir el tipo", **kwargs: Any):
        super().__init__(message, code="AST007", **kwargs)


class InvalidCastError(ASTError):
    """Se intentó una conversión de tipo no permitida."""

    def __init__(self, message: Any = "conversión ilegal", **kwargs: Any):
        super().__init__(message, code="AST008", **kwargs)


class AmbiguousTypeError(ASTError):
    """El tipo es ambiguo y no puede resolverse de forma única."""

    def __init__(self, message: Any = "tipo ambiguo", **kwargs: Any):
        super().__init__(message, code="AST009", **kwargs)


class GenericTypeMismatchError(ASTError):
    """Los argumentos genéricos no son compatibles."""

    def __init__(self, message: Any = "incompatibilidad de tipos genéricos", **kwargs: Any):
        super().__init__(message, code="AST010", **kwargs)


class InvalidTypeArgumentError(ASTError):
    """Se pasó un argumento de tipo inválido a una construcción genérica."""

    def __init__(self, message: Any = "argumento genérico inválido", **kwargs: Any):
        super().__init__(message, code="AST011", **kwargs)


class InvalidReturnTypeError(ASTError):
    """El tipo de retorno no coincide con la firma esperada."""

    def __init__(self, message: Any = "tipo de retorno inválido", **kwargs: Any):
        super().__init__(message, code="AST012", **kwargs)


# Alias de compatibilidad.
invalidASTNode = InvalidASTNodeError
missingASTNode = MissingASTNodeError
unexpectedASTStucture = UnexpectedASTStructureError
unknowType = UnknownTypeError
typeMismatch = TypeMismatchError
cannotInferType = CannotInferTypeError
invalidCast = InvalidCastError
ambigousType = AmbiguousTypeError
genericTypeMismatch = GenericTypeMismatchError
invalidTypeArgument = InvalidTypeArgumentError
invalidReturnType = InvalidReturnTypeError

__all__ = [
    "ASTError",
    "InvalidASTNodeError",
    "MissingASTNodeError",
    "UnexpectedASTStructureError",
    "ASTConstructionError",
    "UnknownTypeError",
    "TypeMismatchError",
    "CannotInferTypeError",
    "InvalidCastError",
    "AmbiguousTypeError",
    "GenericTypeMismatchError",
    "InvalidTypeArgumentError",
    "InvalidReturnTypeError",
    "invalidASTNode",
    "missingASTNode",
    "unexpectedASTStucture",
    "unknowType",
    "typeMismatch",
    "cannotInferType",
    "invalidCast",
    "ambigousType",
    "genericTypeMismatch",
    "invalidTypeArgument",
    "invalidReturnType",
]

    