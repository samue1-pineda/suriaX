from __future__ import annotations

from typing import Any, Optional

try:
    from .error import CompilerError
except ImportError:  # pragma: no cover - compatibility for direct execution
    from error import CompilerError


class ParseError(CompilerError):
    """Base para los errores del parser.

    Se usa cuando el flujo de tokens no encaja con la gramática del lenguaje o
    cuando una construcción sintáctica no puede cerrarse correctamente.
    """

    def __init__(
        self,
        message: Any,
        code: str = "PAR000",
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
            phase="parsing",
            loc=loc,
        )


class SyntaxError(ParseError):
    """Error general de sintaxis."""

    def __init__(self, message: Any = "error de sintaxis", **kwargs: Any):
        super().__init__(message, code="PAR001", **kwargs)


class UnexpectedTokenError(ParseError):
    """Se encontró un token que no corresponde al contexto esperado."""

    def __init__(self, message: Any = "token inesperado", **kwargs: Any):
        super().__init__(message, code="PAR002", **kwargs)


class ExpectedTokenError(ParseError):
    """Se esperaba un token concreto y se recibió otro."""

    def __init__(self, message: Any = "se esperaba un token", **kwargs: Any):
        super().__init__(message, code="PAR003", **kwargs)


class MissingSemicolonError(ParseError):
    """Falta un punto y coma para cerrar una sentencia."""

    def __init__(self, message: Any = "se esperaba ';'", **kwargs: Any):
        super().__init__(message, code="PAR004", **kwargs)


class MissingCommaError(ParseError):
    """Falta una coma en una lista o lista de argumentos."""

    def __init__(self, message: Any = "se esperaba una coma", **kwargs: Any):
        super().__init__(message, code="PAR005", **kwargs)


class UnexpectedCommaError(ParseError):
    """La coma aparece en una posición donde no corresponde."""

    def __init__(self, message: Any = "coma inesperada", **kwargs: Any):
        super().__init__(message, code="PAR006", **kwargs)


class MissingColonError(ParseError):
    """Falta ':' en una construcción como un tipo, diccionario o bloque."""

    def __init__(self, message: Any = "se esperaba ':'", **kwargs: Any):
        super().__init__(message, code="PAR007", **kwargs)


class UnexpectedColonError(ParseError):
    """Se encontró ':' en un lugar no esperado."""

    def __init__(self, message: Any = "':' inesperado", **kwargs: Any):
        super().__init__(message, code="PAR008", **kwargs)


class UnclosedParenthesisError(ParseError):
    """No se cerró un paréntesis."""

    def __init__(self, message: Any = "paréntesis no cerrado", **kwargs: Any):
        super().__init__(message, code="PAR009", **kwargs)


class UnclosedBracketError(ParseError):
    """No se cerró un corchete."""

    def __init__(self, message: Any = "corchete no cerrado", **kwargs: Any):
        super().__init__(message, code="PAR010", **kwargs)


class UnclosedBraceError(ParseError):
    """No se cerró una llave."""

    def __init__(self, message: Any = "llave no cerrada", **kwargs: Any):
        super().__init__(message, code="PAR011", **kwargs)


class InvalidExpressionError(ParseError):
    """La expresión no encaja con la gramática esperada."""

    def __init__(self, message: Any = "expresión mal formada", **kwargs: Any):
        super().__init__(message, code="PAR012", **kwargs)


class InvalidStatementError(ParseError):
    """La sentencia no es válida en el contexto actual."""

    def __init__(self, message: Any = "sentencia inválida", **kwargs: Any):
        super().__init__(message, code="PAR013", **kwargs)


class UnexpectedEOFError(ParseError):
    """El archivo terminó antes de completar una construcción."""

    def __init__(self, message: Any = "fin de archivo inesperado", **kwargs: Any):
        super().__init__(message, code="PAR014", **kwargs)


class DuplicatedModifierError(ParseError):
    """Se repitió un modificador que no debe aparecer dos veces."""

    def __init__(self, message: Any = "modificador duplicado", **kwargs: Any):
        super().__init__(message, code="PAR015", **kwargs)


class InvalidTypeDeclarationError(ParseError):
    """La declaración de un tipo (``struct``, ``enum`` o ``type``) es inválida.

    Cubre los tokens ``STRUCT`` / ``ENUM`` / ``TYPE``: nombre ausente, cuerpo
    mal formado o campos sin tipo.
    """

    def __init__(self, message: Any = "declaración de tipo inválida", **kwargs: Any):
        super().__init__(message, code="PAR016", **kwargs)


class InvalidFunctionSignatureError(ParseError):
    """La firma de una función (``fn``) no es válida.

    Cubre el token ``FUNCTION``: parámetros mal formados, falta de ``->`` o de
    tipo de retorno.
    """

    def __init__(self, message: Any = "firma de función inválida", **kwargs: Any):
        super().__init__(message, code="PAR017", **kwargs)


class InvalidMatchArmError(ParseError):
    """Una rama de ``match`` (``case``) no está bien formada.

    Cubre los tokens ``MATCH`` / ``CASE``: patrón ausente, falta de ``:`` o
    cuerpo de rama inválido.
    """

    def __init__(self, message: Any = "rama de 'match' inválida", **kwargs: Any):
        super().__init__(message, code="PAR018", **kwargs)


class InvalidDecoratorTargetError(ParseError):
    """Un decorador (``@``) no se aplica sobre una construcción válida.

    Cubre el token ``DECORATOR``: un ``@nombre`` que no precede a una función u
    otra declaración decorable.
    """

    def __init__(self, message: Any = "decorador sin objetivo válido", **kwargs: Any):
        super().__init__(message, code="PAR019", **kwargs)


class UnknownDirectiveError(ParseError):
    """La directiva (``#``) no es reconocida por el parser o está mal usada.

    Cubre el token ``DIRECTIVE``: el lexer valida que el nombre exista, pero el
    parser valida su uso (p. ej. ``#test`` con un objetivo desconocido o una
    directiva en una posición no permitida).
    """

    def __init__(self, message: Any = "directiva desconocida o mal ubicada", **kwargs: Any):
        super().__init__(message, code="PAR020", **kwargs)


class InvalidMemoryQualifierError(ParseError):
    """Un cualificador de memoria se usó en una posición sintáctica inválida.

    Cubre los tokens del modelo *ownership + move-semantics*: ``MOVE``,
    ``FREE``, ``POINTER`` (``ptr``) y ``ADDRESS`` (``&``) cuando aparecen donde
    la gramática no los admite. La validación semántica (propiedad, uso tras
    move) NO ocurre aquí, sino en la fase de semántica / lowering a MIR.
    """

    def __init__(self, message: Any = "cualificador de memoria mal ubicado", **kwargs: Any):
        super().__init__(message, code="PAR021", **kwargs)


class MissingTypeAnnotationError(ParseError):
    """Falta la anotación de tipo donde el lenguaje la exige.

    suriaX es de tipado estático fuerte y nominal: un binding o parámetro sin
    su tipo correspondiente es un error sintáctico.
    """

    def __init__(self, message: Any = "se esperaba una anotación de tipo", **kwargs: Any):
        super().__init__(message, code="PAR023", **kwargs)


class InvalidExternBlockError(ParseError):
    """El bloque de interoperabilidad ``#extern cpp{ ... }`` es inválido.

    Cubre el token ``RAW_BLOCK`` y su contexto: objetivo del ``#extern`` no
    soportado (sólo ``cpp``), falta del cuerpo crudo, o uso del bloque en una
    posición no permitida. El contenido C++ en sí se valida en el backend C++,
    no aquí.
    """

    def __init__(self, message: Any = "bloque '#extern' inválido", **kwargs: Any):
        super().__init__(message, code="PAR024", **kwargs)


class ExpressionTooDeepError(ParseError):
    """La construcción anidada excede la profundidad de recursión soportada.

    El parser usa llamadas recursivas para leer paréntesis, prefijos unarios y
    otras estructuras anidadas. Cuando el anidamiento es extremo, se convierte
    el fallo en un diagnóstico controlado en vez de dejar un traceback.
    """

    def __init__(self, message: Any = "expresión demasiado anidada", **kwargs: Any):
        super().__init__(message, code="PAR025", **kwargs)


class InvalidLibraryNameError(ParseError):
    """Un componente de ``lib_name`` (``#import a.b``) no puede nombrar un módulo.

    Caso típico: el alias de un ``#export`` coincide con una palabra
    reservada (``#import io.str``). El ``expect(IDENTIFIER)`` genérico
    reportaría el TOKEN encontrado (``STR``), que no dice nada al usuario;
    esto nombra la causa y la salida.
    """

    def __init__(self, message: Any = "nombre de módulo inválido", **kwargs: Any):
        super().__init__(message, code="PAR026", **kwargs)


class ExitFromFinallyError(ParseError):
    """``return``, ``break`` o ``continue`` que SALE de un bloque ``finally``.

    Un ``finally`` corre porque el ``try`` ya esta saliendo —con un valor, por
    un salto o con una excepcion en vuelo—. Salir del ``finally`` con otro
    salto reemplazaria esa salida en silencio: un ``return`` dentro de un
    ``finally`` se tragaria la excepcion que viajaba. Es la regla de PEP 765
    en Python y de C# (CS0157). Un ``break`` de un bucle que esta DENTRO del
    ``finally`` si vale: no sale de el.
    """

    def __init__(self, message: Any = "salto que sale de un 'finally'", **kwargs: Any):
        super().__init__(message, code="PAR027", **kwargs)


class WithReceiverError(ParseError):
    """``.campo`` sin un ``with`` de UN valor alrededor.

    Dentro de ``with (ventana) { .ancho = 900; }`` el punto dice "del valor
    del with". Fuera de un ``with`` no hay a quien referirse, y con varios
    valores (``with (a, b)``) no se sabria de cual.
    """

    def __init__(self, message: Any = "'.campo' fuera de un 'with'", **kwargs: Any):
        super().__init__(message, code="PAR028", **kwargs)


# Alias de compatibilidad.
syntaxError = SyntaxError
unexpectedToken = UnexpectedTokenError
expectedToken = ExpectedTokenError
missingSemicolon = MissingSemicolonError
missingComma = MissingCommaError
unexpectedComma = UnexpectedCommaError
missingColon = MissingColonError
unexpectedColon = UnexpectedColonError
unclosedParenthesis = UnclosedParenthesisError
unclsoedBracket = UnclosedBracketError
unclosedBrace = UnclosedBraceError
invalidExpression = InvalidExpressionError
invalidStatement = InvalidStatementError
unexpectedEOF = UnexpectedEOFError
duplicatedModifier = DuplicatedModifierError
invalidTypeDeclaration = InvalidTypeDeclarationError
invalidFunctionSignature = InvalidFunctionSignatureError
invalidMatchArm = InvalidMatchArmError
invalidDecoratorTarget = InvalidDecoratorTargetError
unknownDirective = UnknownDirectiveError
invalidMemoryQualifier = InvalidMemoryQualifierError
missingTypeAnnotation = MissingTypeAnnotationError
invalidExternBlock = InvalidExternBlockError
expressionTooDeep = ExpressionTooDeepError
invalidLibraryName = InvalidLibraryNameError

__all__ = [
    "ParseError",
    "SyntaxError",
    "UnexpectedTokenError",
    "ExpectedTokenError",
    "MissingSemicolonError",
    "MissingCommaError",
    "UnexpectedCommaError",
    "MissingColonError",
    "UnexpectedColonError",
    "UnclosedParenthesisError",
    "UnclosedBracketError",
    "UnclosedBraceError",
    "InvalidExpressionError",
    "InvalidStatementError",
    "UnexpectedEOFError",
    "DuplicatedModifierError",
    "InvalidTypeDeclarationError",
    "InvalidFunctionSignatureError",
    "InvalidMatchArmError",
    "InvalidDecoratorTargetError",
    "UnknownDirectiveError",
    "InvalidMemoryQualifierError",
    "MissingTypeAnnotationError",
    "InvalidExternBlockError",
    "ExpressionTooDeepError",
    "InvalidLibraryNameError",
    "ExitFromFinallyError",
    "WithReceiverError",
    "syntaxError",
    "unexpectedToken",
    "expectedToken",
    "missingSemicolon",
    "missingComma",
    "unexpectedComma",
    "missingColon",
    "unexpectedColon",
    "unclosedParenthesis",
    "unclsoedBracket",
    "unclosedBrace",
    "invalidExpression",
    "invalidStatement",
    "unexpectedEOF",
    "duplicatedModifier",
    "invalidTypeDeclaration",
    "invalidFunctionSignature",
    "invalidMatchArm",
    "invalidDecoratorTarget",
    "unknownDirective",
    "invalidMemoryQualifier",
    "missingTypeAnnotation",
    "invalidExternBlock",
    "expressionTooDeep",
    "invalidLibraryName",
]
