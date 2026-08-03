"""``type = base_type { type_suffix }`` (EBNF secc. 4).

::

    base_type   = "int" | "float" | "bool" | "char" | "str" | "void"
                | "type"
                | qualified_name
    qualified_name = NAME { "." NAME }        (* NAME = IDENTIFIER | DUNDER *)
    type_suffix = "?" | "ptr" [ "mutable" ]

``ptr`` es un sufijo POSTFIJO (decision de usuario): ``char ptr`` es "puntero
a char" (``char *text`` en C), no ``ptr char``. La forma prefija ya no se
acepta -- ``_parse_base_type`` la reporta con una migracion dirigida.

Los sufijos se aplican de IZQUIERDA A DERECHA, asi que el orden desambigua
lo que en prefijo no se podia escribir:

    char ptr        ->  puntero a char
    char ptr mutable->  puntero a char, escribible a traves de el
    char ptr?       ->  puntero NULLABLE a char        (ptr, luego ?)
    char? ptr       ->  puntero a (char nullable)      (?, luego ptr)
    char ptr ptr    ->  puntero a puntero a char

``ptr T`` es de solo lectura A TRAVES del puntero; ``ptr mutable`` permite
escribir a traves de el (const-correctness estilo C). La mutabilidad del
BINDING es aparte (``var``/``const``, ver statements.py).

``type`` como base_type es el METATIPO (el tipo de un tipo): habilita
``fn _block_def(int len) -> type``. La DECLARACION de un tipo opaco
(``const type int8;``) la parsea ``statements.parse_type_decl``.

``qualified_name`` con puntos (``dt.int8``) referencia un tipo publicado por
una libreria importada: las librerias declaran tipos no nativos
(``int8``/``float16``...) y el consumidor los usa como cualquier otro tipo.
Aqui solo se transporta el nombre completo; recorrer los miembros hasta el
simbolo es de la Semantica (``semantic/type_service.lookup_type_path``).
"""

from __future__ import annotations

from typing import Dict

try:
    from include import ast_nodes as ast
    from include.t_types import TokenType
    from error_handler import ParseError
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from t_types import TokenType  # type: ignore
    import ParseError  # type: ignore

from ..context import ParserContext
from ..cursor import Cursor

_PRIMITIVE_TOKENS: Dict[TokenType, str] = {
    TokenType.VOID: "void",
    TokenType.BOOL: "bool",
    TokenType.INT: "int",
    TokenType.FLOAT: "float",
    TokenType.CHAR: "char",
    TokenType.STR: "str",
}


def parse_type(cursor: Cursor, ctx: ParserContext) -> ast.TypeExpr:
    base = _parse_base_type(cursor, ctx)
    # sufijos postfijos, aplicados en el orden en que se escriben (izq->der):
    # 'char? ptr' != 'char ptr?' (ver el docstring del modulo).
    while True:
        tok = cursor.peek()
        if tok.type is TokenType.NULLABLE:
            cursor.advance()
            base = ast.NullableTypeExpr(ln=tok.ln, col=tok.col, inner=base)
        elif tok.type is TokenType.POINTER:
            cursor.advance()
            is_mutable = cursor.match(TokenType.MUTABLE)  # 'T ptr mutable'
            base = ast.PointerTypeExpr(ln=tok.ln, col=tok.col, inner=base,
                                        mutable=is_mutable)
        else:
            return base


def _parse_base_type(cursor: Cursor, ctx: ParserContext) -> ast.TypeExpr:
    tok = cursor.peek()

    name = _PRIMITIVE_TOKENS.get(tok.type)
    if name is not None:
        cursor.advance()
        return ast.PrimitiveTypeExpr(ln=tok.ln, col=tok.col, name=name)

    if tok.type is TokenType.ERRORTYPE:
        # 'error T' (union T-o-error) o 'error' a secas. El inner es OTRO
        # 'type' completo; ausente si lo que sigue no arranca un tipo
        # ('error n;' -> 'error' solo, 'n' es el nombre del binding).
        cursor.advance()
        inner = _parse_error_inner(cursor, ctx)
        return ast.ErrorTypeExpr(ln=tok.ln, col=tok.col, inner=inner)

    if tok.type is TokenType.TYPE:
        # el METATIPO: 'fn f() -> type' devuelve un tipo como valor.
        cursor.advance()
        return ast.MetaTypeExpr(ln=tok.ln, col=tok.col)

    if tok.type is TokenType.IDENTIFIER and tok.lexeme == "self":
        # 'self' en posicion de tipo es el placeholder del tipo que hara
        # '@impl' (solo valido dentro de un prototipo de trait; la Semantica
        # lo rechaza en otra posicion). NO es keyword: 'self' sigue usable como
        # nombre de variable/parametro. No se cualifica ('self.x' no es un tipo).
        cursor.advance()
        return ast.SelfTypeExpr(ln=tok.ln, col=tok.col)

    if tok.type is TokenType.IDENTIFIER or tok.type is TokenType.DUNDER:
        # DUNDER: un tipo nominal declarado con nombre '__x__' (ver
        # Cursor.expect_name) tambien debe poder REFERENCIARSE como tipo
        # (p. ej. '__opaque__ ptr'), no solo declararse.
        cursor.advance()
        return ast.NominalTypeExpr(ln=tok.ln, col=tok.col,
                                    name=_qualified_name(cursor, tok.lexeme))

    if tok.type is TokenType.POINTER:
        # forma prefija ('ptr char') retirada: 'ptr' es sufijo postfijo.
        raise ParseError.MissingTypeAnnotationError(
            "'ptr' es un sufijo postfijo: escribe 'T ptr' en vez de 'ptr T' "
            "(p. ej. 'char ptr text', no 'ptr char text')",
            line=tok.ln, column=tok.col,
        )

    raise ParseError.MissingTypeAnnotationError(
        f"se esperaba un tipo, se encontro {tok.type.name}",
        line=tok.ln, column=tok.col,
    )


# tokens que pueden ARRANCAR un tipo base (para decidir el inner de 'error').
_TYPE_STARTERS = frozenset({
    *_PRIMITIVE_TOKENS, TokenType.TYPE, TokenType.ERRORTYPE,
    TokenType.IDENTIFIER, TokenType.DUNDER,
})


def _parse_error_inner(cursor: Cursor, ctx: ParserContext):
    """El tipo envuelto por ``error``, o ``None`` si ``error`` va solo.

    Regla GREEDY sin backtracking: hay inner sii el token siguiente arranca
    un tipo. Asi ``error int n`` -> ``error<int>`` + nombre ``n``;
    ``fn f() -> error`` (sigue ``;``) -> ``error`` sola. La unica forma no
    escribible es un binding de tipo ``error`` puro seguido de nombre
    (``error n;``): usa ``error void n;`` o reordena — caso marginal."""
    if cursor.peek().type in _TYPE_STARTERS:
        return parse_type(cursor, ctx)
    return None


def parse_type_args(cursor: Cursor, ctx: ParserContext) -> list[ast.TypeExpr]:
    """``type_args = "<" type { "," type } ">"`` -- posicion de ARGUMENTOS DE
    TIPO (EBNF secc. 4).

    Regla COMPARTIDA por toda construccion que parametrice con tipos: hoy la
    usa ``cast<T>(expr)`` (unica forma nativa); las librerias la reutilizaran
    para genericos (``vec<int>``) sin redefinir la sintaxis de los angulos.

    Aqui ``<``/``>`` no son comparaciones: el llamador YA decidio que esta en
    posicion de argumentos de tipo (p. ej. tras la keyword ``cast``), asi que
    no hay ambiguedad estilo C++ que resolver en este nivel.
    """
    cursor.expect(TokenType.LESS)
    args = [parse_type(cursor, ctx)]
    while cursor.match(TokenType.COMMA):
        args.append(parse_type(cursor, ctx))
    cursor.expect(TokenType.GREATER)
    return args


def _qualified_name(cursor: Cursor, head: str) -> str:
    """``head { "." NAME }`` -> ``"dt"`` / ``"dt.int8"`` / ``"d_types.dt.int8"``.

    El primer nombre ya viene consumido. Sin puntos (el caso comun) no se
    construye ninguna lista: se devuelve ``head`` tal cual.
    """
    if not cursor.check(TokenType.DOT):
        return head
    parts = [head]
    while cursor.match(TokenType.DOT):
        parts.append(cursor.expect_name().lexeme)
    return ".".join(parts)


__all__ = ["parse_type", "parse_type_args"]
