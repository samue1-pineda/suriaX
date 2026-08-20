from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class TokenType(Enum):
    # --- literales / identificadores ---
    IDENTIFIER = 1
    CHAR_LIT = 2       # 'x'   (literal de caracter)
    INT_LIT = 3        # 10    (literal entero)
    FLOAT_LIT = 4      # 3.14  (literal flotante)
    STRING_LIT = 5     # "..." plana o f"..." interpolada (mismo token; ver StringValue)
    TRUE = 6
    FALSE = 7
    NULL = 8

    # --- tipos primitivos (palabras clave de tipo, NO literales) ---
    VOID = 10
    BOOL = 11
    TYPE = 12          # 'type' se construye del struct
    INT = 13           # 'int'   (tipo; el literal entero es INT_LIT)
    FLOAT = 14         # 'float' (tipo; el literal flotante es FLOAT_LIT)
    CHAR = 22          # 'char'  (tipo; el literal de caracter es CHAR_LIT)
    STR = 23           # 'str'   (tipo; el literal de cadena es STRING_LIT)

    # --- declaracion / bindings ---
    CONST = 15
    MUTABLE = 16       # 'mutable': califica PUNTEROS ('ptr mutable T')
    VAR = 24           # 'var': binding mutable ('var int x = 10;')
    FUNCTION = 17      # 'fn'
    STRUCT = 18
    ENUM = 19
    SIZEOF = 20
    DUNDER = 21        # __foo__  (FORMA de un nombre; NO implica hook, ver HOOK/DUNDER_KW)

    # --- visibilidad (reservas): prefijo opcional de una declaracion top-level ---
    # sin token = publico (default). 'private' = mismo paquete; 'internal' = mismo archivo.
    PUBLIC = 34
    PRIVATE = 35
    INTERNAL = 36

    # --- especificador de metodo especial (antes se ADIVINABA por la forma __x__) ---
    HOOK = 37          # 'hook': metodo del set fijo del compilador (free/sizeof/print/len/cast)
    DUNDER_KW = 38     # 'dunder': metodo especial LIBRE del usuario ('dunder fn __xxx__()')

    # --- control de flujo ---
    IF = 25
    ELSE = 26
    WHILE = 27
    RETURN = 28
    MATCH = 29
    CASE = 30
    BREAK = 31
    CONTINUE = 32
    TEST = 33          # funcion nativa 'test' (NO la directiva #test)

    # --- memoria: ownership + move-semantics ---
    # Los valores 40-42, 44-45, 47-48 y 57-58 quedaron LIBRES al retirar el
    # modelo por regiones en v0.2.0 (REGION/IN/AT/SHRD/NA/alloc/MAKE/NEW/
    # DELETE). No se reutilizan: un volcado de tokens viejo mostraria un
    # nombre distinto para el mismo numero y no habria como notarlo.
    MOVE = 43          # 'move', transferencia de propiedad (move-semantics)
    FREE = 46          # 'free', destruccion anticipada de un valor con dueno
    POINTER = 49       # 'ptr'
    ADDRESS = 50       # '&'
    NULLABLE = 51      # '?'
    CAST = 52          # 'cast': conversion explicita 'cast<T>(expr)'

    # --- manejo de errores (excepciones) ---
    ERRORTYPE = 53     # 'error': tipo union 'error T' / 'error' (NO el synthetic ERROR=98)
    TRY = 54           # 'try', abre un bloque protegido
    CATCH = 55         # 'catch', captura el error propagado
    THROW = 56         # 'throw', inicia la propagacion

    # --- operadores aritmeticos ---
    ASSIGN = 60        # =
    PLUS = 61          # +
    MINUS = 62         # -
    MULTIPLY = 63      # *
    DIVIDE = 64        # /
    MODULO = 72        # %  (resto de la division entera)

    # --- asignacion compuesta e incremento ---
    # AZUCAR: el parser los desazucara ('n += 2' -> 'n = n + 2'), asi que no
    # llegan al AST ni al HIR. Solo existen como tokens.
    PLUS_ASSIGN = 73     # +=
    MINUS_ASSIGN = 74    # -=
    STAR_ASSIGN = 78     # *=
    SLASH_ASSIGN = 79    # /=
    PERCENT_ASSIGN = 91  # %=
    INCREMENT = 92       # ++
    DECREMENT = 93       # --

    # --- operadores de comparacion ---
    EQUAL = 65         # ==
    NOT_EQUAL = 66     # !=
    LESS = 67          # <
    LESS_EQUAL = 68    # <=
    GREATER = 69       # >
    GREATER_EQUAL = 70 # >=

    # --- flecha de retorno ---
    ARROW = 71         # ->  (firma de funcion: 'fn f() -> int')

    # --- operadores logicos ---
    AND = 75           # and
    OR = 76            # or
    NOT = 77           # not

    # --- delimitadores ---
    L_PAREN = 80       # (
    R_PAREN = 81       # )
    L_BRACE = 82       # {
    R_BRACE = 83       # }
    L_BRACKET = 84     # [
    R_BRACKET = 85     # ]
    DOT = 86           # .
    COMMA = 87         # ,
    SEMICOLON = 88     # ;
    COLON = 89         # :

    # --- especiales ---
    DECORATOR = 95     # '@', sobre la funcion como en python
    DIRECTIVE = 96     # '#', la directiva se identifica en el parser
    RAW_BLOCK = 97     # contenido crudo de '#extern cpp{ ... }' (sin tokenizar)

    ERROR = 98         # token sintetico ante un error lexico
    EOF = 100


# --- tablas de busqueda O(1) usadas por los scanners ---
#
# se construyen una sola vez al importar el modulo. evitar diccionarios por
# token en caliente es clave para el rendimiento del lexer: el scanner de
# identificadores hace un unico KEYWORDS.get(lexema) en lugar de comparar
# string por string.

KEYWORDS: dict[str, TokenType] = {
    # tipos / literales
    "char": TokenType.CHAR,
    "int": TokenType.INT,
    "float": TokenType.FLOAT,
    "str": TokenType.STR,
    "bool": TokenType.BOOL,
    "void": TokenType.VOID,
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
    "null": TokenType.NULL,
    "type": TokenType.TYPE,
    # declaracion
    "const": TokenType.CONST,
    "var": TokenType.VAR,
    "mutable": TokenType.MUTABLE,  # tipos puntero ('ptr mutable T')
    "fn": TokenType.FUNCTION,
    "struct": TokenType.STRUCT,
    "enum": TokenType.ENUM,
    "sizeof": TokenType.SIZEOF,
    # visibilidad (reservas): sin token = publico
    "public": TokenType.PUBLIC,
    "private": TokenType.PRIVATE,
    "internal": TokenType.INTERNAL,
    # especificador de metodo especial (ya no se adivina por la forma __x__)
    "hook": TokenType.HOOK,
    "dunder": TokenType.DUNDER_KW,
    # manejo de errores (excepciones)
    "error": TokenType.ERRORTYPE,
    "try": TokenType.TRY,
    "catch": TokenType.CATCH,
    "throw": TokenType.THROW,
    # control de flujo
    "if": TokenType.IF,
    "else": TokenType.ELSE,
    "while": TokenType.WHILE,
    "return": TokenType.RETURN,
    "match": TokenType.MATCH,
    "case": TokenType.CASE,
    "break": TokenType.BREAK,
    "continue": TokenType.CONTINUE,
    "test": TokenType.TEST,
    # memoria: ownership + move-semantics
    "move": TokenType.MOVE,
    "free": TokenType.FREE,
    # 'region', 'shrd', 'na', 'in', 'at', 'new', 'delete' y 'make' NO son
    # palabras clave: pertenecian al modelo por regiones, retirado en v0.2.0
    # (ver documentation/source/memory_decision.rst). Al dejar de reservarlas
    # quedan disponibles como nombres corrientes — justo los nombres naturales
    # de una libreria de memoria ('fn new(int n) -> ptr int', 'arena.delete').
    "ptr": TokenType.POINTER,
    "cast": TokenType.CAST,
    # operadores logicos (son palabras, no simbolos)
    "and": TokenType.AND,
    "or": TokenType.OR,
    "not": TokenType.NOT,
}

# directivas nativas reconocidas tras un '#'. el lexer solo valida que el
# nombre exista; la semantica de cada directiva vive en el parser.
DIRECTIVES: frozenset[str] = frozenset(
    {"import", "export", "extern", "test", "from"}
)


@dataclass(slots=True, frozen=True)
class Interp:
    """Referencia interpolada dentro de una f-string: el ``a`` de ``f"hola{a}"``.

    Solo una f-string (prefijo ``f``) produce segmentos ``Interp``; una
    cadena plana ``"..."`` nunca interpola (``{``/``}`` son literales).

    Por ahora solo guarda el texto crudo de la expresion (``expr``). El parser
    es quien la analizara como una expresion real; el lexer solo la delimita.
    ``col`` es la columna (1-based) donde empieza la expresion en el fuente,
    util para reportar errores precisos.
    """

    expr: str
    col: int

    def __repr__(self) -> str:
        return f"Interp({self.expr!r})"


@dataclass(slots=True, frozen=True)
class StringValue:
    """Valor de un literal de cadena, posiblemente interpolado.

    ``parts`` es una lista de segmentos en orden: cada elemento es ``str``
    (texto literal ya con escapes resueltos) o :class:`Interp` (una
    interpolacion ``{expr}``). Un string sin interpolacion tiene un unico
    segmento ``str`` (o ninguno si esta vacio).

    Se construye en una sola pasada por el scanner. ``is_interpolated``
    permite a fases posteriores tomar el camino rapido cuando no hay ``{}``.
    """

    parts: tuple

    @property
    def is_interpolated(self) -> bool:
        return any(isinstance(p, Interp) for p in self.parts)

    def flat(self) -> str:
        """Texto plano uniendo solo los segmentos literales (sin resolver {})."""
        return "".join(p for p in self.parts if isinstance(p, str))

    def __repr__(self) -> str:
        return f"Str({list(self.parts)!r})"


@dataclass(slots=True)
class Token:
    type: TokenType
    lexeme: str
    value: Any
    ln: int
    col: int

    def __repr__(self) -> str:
        # repr compacto en una sola linea para volcar listas de tokens
        # sin ruido visual (usado por la directiva '#test lexer').
        return (
            f"Token({self.type.name}, {self.lexeme!r}, "
            f"{self.value!r}, {self.ln}:{self.col})"
        )
