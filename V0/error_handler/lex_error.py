from __future__ import annotations

from typing import Optional, Any

try:
    from .error import CompilerError
except ImportError:  # pragma: no cover - compatibility for direct execution
    from error import CompilerError


class LexError(CompilerError):
    """Base para todos los errores del lexer.

    Estos problemas suceden durante el primer paso del pipeline y suelen
    estar asociados a caracteres, literales, directivas o límites del flujo
    de entrada.
    """

    def __init__(
        self,
        message: Any,
        code: str = "LEX000",
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
            phase="lexing",
            loc=loc,
        )


class UnexpectedCharacterError(LexError):
    """Se encontró un carácter que el lexer no reconoce."""

    def __init__(self, message: Any = "carácter no reconocido", **kwargs: Any):
        super().__init__(message, code="LEX001", **kwargs)


class InvalidTokenError(LexError):
    """La secuencia leída no puede convertirse en un token válido."""

    def __init__(self, message: Any = "secuencia de token mal formada", **kwargs: Any):
        super().__init__(message, code="LEX002", **kwargs)


class UnterminatedStringError(LexError):
    """La cadena de texto no cerró correctamente."""

    def __init__(self, message: Any = "cadena de texto no cerrada", **kwargs: Any):
        super().__init__(message, code="LEX003", **kwargs)


class UnterminatedCommentError(LexError):
    """El comentario multilínea terminó sin cerrar."""

    def __init__(self, message: Any = "comentario multilínea no cerrado", **kwargs: Any):
        super().__init__(message, code="LEX004", **kwargs)


class InvalidEscapeSequenceError(LexError):
    """Se detectó una secuencia de escape inválida dentro de una cadena."""

    def __init__(self, message: Any = "secuencia de escape inválida", **kwargs: Any):
        super().__init__(message, code="LEX005", **kwargs)


class NumericLiteralOverflowError(LexError):
    """Un literal numérico excede el rango soportado."""

    def __init__(self, message: Any = "literal numérico demasiado grande", **kwargs: Any):
        super().__init__(message, code="LEX006", **kwargs)


class InvalidNumberFormatError(LexError):
    """El número no sigue la sintaxis esperada."""

    def __init__(self, message: Any = "formato numérico no válido", **kwargs: Any):
        super().__init__(message, code="LEX007", **kwargs)


class InvalidUnicodeCharacterError(LexError):
    """Se encontró un carácter Unicode no válido para el lexer."""

    def __init__(self, message: Any = "carácter Unicode no válido", **kwargs: Any):
        super().__init__(message, code="LEX008", **kwargs)


class UnexpectedEOFError(LexError):
    """El archivo terminó antes de completar un token o una estructura."""

    def __init__(self, message: Any = "fin de archivo inesperado", **kwargs: Any):
        super().__init__(message, code="LEX009", **kwargs)


class InvalidDirectiveError(LexError):
    """La directiva encontrada no es válida o no está soportada."""

    def __init__(self, message: Any = "directiva inválida", **kwargs: Any):
        super().__init__(message, code="LEX010", **kwargs)


class InvalidIdentifierError(LexError):
    """El identificador no cumple con las reglas sintácticas del lenguaje."""

    def __init__(self, message: Any = "identificador inválido", **kwargs: Any):
        super().__init__(message, code="LEX011", **kwargs)


class InvalidCharacterLiteralError(LexError):
    """El literal de carácter está vacío o contiene más de un code point.

    Lo usa el scanner de ``'x'``: a diferencia de
    :class:`UnterminatedStringError` (que aplica cuando falta el delimitador de
    cierre), este error señala que el literal sí cerró pero su contenido no es
    exactamente un único carácter Unicode (``''`` o ``'ab'``).
    """

    def __init__(self, message: Any = "literal de carácter inválido", **kwargs: Any):
        super().__init__(message, code="LEX012", **kwargs)


class InvalidDecoratorError(LexError):
    """El decorador iniciado con ``@`` no cumple la sintaxis esperada.

    Cubre el token ``DECORATOR``: un ``@`` que no va seguido de un
    identificador válido (p. ej. ``@`` solo, ``@123`` o ``@ algo``).
    """

    def __init__(self, message: Any = "decorador inválido", **kwargs: Any):
        super().__init__(message, code="LEX013", **kwargs)


class UnterminatedExternBlockError(LexError):
    """El bloque ``#extern cpp{ ... }`` no se cerró.

    El contenido del bloque ``extern`` se captura como texto crudo (``RAW_BLOCK``)
    sin tokenizarse con las reglas de suriaX; si no se encuentra la ``}`` que
    cierra el bloque antes del fin del archivo, se reporta este error.
    """

    def __init__(self, message: Any = "bloque '#extern' sin cerrar", **kwargs: Any):
        super().__init__(message, code="LEX014", **kwargs)


# Alias para mantener compatibilidad con el módulo anterior.
unexpectedCharacter = UnexpectedCharacterError
invalidToken = InvalidTokenError
unterminatedString = UnterminatedStringError
unterminatedComment = UnterminatedCommentError
invalidEscapeSequence = InvalidEscapeSequenceError
numericLiteralOverflow = NumericLiteralOverflowError
invalidNumberFormat = InvalidNumberFormatError
invalidUnicodeCharacter = InvalidUnicodeCharacterError
unexpectedEOF = UnexpectedEOFError
invalidDirective = InvalidDirectiveError
invalidIdentifier = InvalidIdentifierError
invalidCharacterLiteral = InvalidCharacterLiteralError
invalidDecorator = InvalidDecoratorError
unterminatedExternBlock = UnterminatedExternBlockError

__all__ = [
    "LexError",
    "UnexpectedCharacterError",
    "InvalidTokenError",
    "UnterminatedStringError",
    "UnterminatedCommentError",
    "InvalidEscapeSequenceError",
    "NumericLiteralOverflowError",
    "InvalidNumberFormatError",
    "InvalidUnicodeCharacterError",
    "UnexpectedEOFError",
    "InvalidDirectiveError",
    "InvalidIdentifierError",
    "InvalidCharacterLiteralError",
    "InvalidDecoratorError",
    "UnterminatedExternBlockError",
    "unexpectedCharacter",
    "invalidToken",
    "unterminatedString",
    "unterminatedComment",
    "invalidEscapeSequence",
    "numericLiteralOverflow",
    "invalidNumberFormat",
    "invalidUnicodeCharacter",
    "unexpectedEOF",
    "invalidDirective",
    "invalidIdentifier",
    "invalidCharacterLiteral",
    "invalidDecorator",
    "unterminatedExternBlock",
]
