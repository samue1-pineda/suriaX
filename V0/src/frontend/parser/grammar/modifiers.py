"""Prefijo de modificadores de un item top-level y despacho del item.

Un item de nivel superior puede llevar, en ORDEN FIJO:

::
    top_level = [ "@" deco [args] ] [ visibility ] [ hook | dunder ] declaration
    visibility = "public" | "private" | "internal"        (sin token = publico)

El **decorador** (si lo hay) va PRIMERO y es dueño de su propio prefijo (ver
``grammar/decorators.py``): ``@impl(x) public struct ...``. Sin decorador, la
**visibilidad** precede al **especificador** (``hook``/``dunder``), que solo
precede a ``fn``. Las **directivas** (``#import``/...) y ``test`` NO llevan
prefijo.

Este modulo es el unico dueño de "que inicia un item top-level y con que
prefijo": ``program.py`` queda como bucle + recuperacion. Es el equivalente
top-level de ``statements.parse_statement`` para el nivel de bloque.
"""

from __future__ import annotations

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
from .block import parse_block
from .decorators import parse_decorator_decl
from .directives import parse_directive
from .enums import parse_enum_decl
from .functions import parse_function_decl
from .prefixes import consume_specifier, consume_visibility
from .statements import parse_statement
from .structs import parse_struct_decl


def parse_top_level_item(cursor: Cursor, ctx: ParserContext) -> ast.ASTNode:
    tok = cursor.peek()
    # directivas y 'test' no admiten prefijo de modificadores.
    if tok.type is TokenType.DIRECTIVE:
        return parse_directive(cursor, ctx)
    if tok.type is TokenType.TEST:
        return _parse_test_decl(cursor, ctx)
    # el decorador va PRIMERO y es dueño de su propio prefijo (visibilidad,
    # especificador y, para '@trait', su cuerpo): '@impl(x) public struct ...'.
    if tok.type is TokenType.DECORATOR:
        return parse_decorator_decl(cursor, ctx)

    visibility = consume_visibility(cursor)

    specifier = consume_specifier(cursor)
    if specifier is not None:
        if not cursor.check(TokenType.FUNCTION):
            nxt = cursor.peek()
            raise ParseError.ExpectedTokenError(
                f"'{specifier}' solo puede preceder a 'fn', se encontro "
                f"{nxt.type.name}",
                line=nxt.ln, column=nxt.col,
            )
        return parse_function_decl(cursor, ctx, visibility=visibility,
                                   specifier=specifier)

    tok = cursor.peek()
    if tok.type is TokenType.FUNCTION:
        return parse_function_decl(cursor, ctx, visibility=visibility)
    if tok.type is TokenType.STRUCT:
        return parse_struct_decl(cursor, ctx, visibility=visibility)
    if tok.type is TokenType.ENUM:
        return parse_enum_decl(cursor, ctx, visibility=visibility)
    # binding top-level (const/var/type/tipo-keyword/IDENTIFIER=#import) o
    # cualquier otra sentencia; 'parse_statement' adjunta la visibilidad si
    # recae sobre un binding que la admite y la rechaza en otro caso.
    return parse_statement(cursor, ctx, visibility=visibility)


def _parse_test_decl(cursor: Cursor, ctx: ParserContext) -> ast.TestDecl:
    """``test STRING_LIT block`` -- bloque de prueba nombrado (estilo Zig).

    Declaracion de primer nivel: el runner ejecuta su cuerpo, la compilacion
    normal solo lo valida (ver ``ast_nodes.TestDecl``)."""
    tok = cursor.expect(TokenType.TEST)
    name_tok = cursor.expect(TokenType.STRING_LIT)
    name = name_tok.value.flat() if hasattr(name_tok.value, "flat") else str(name_tok.value)
    body = parse_block(cursor, ctx)
    cursor.match(TokenType.SEMICOLON)  # ';' opcional tras el bloque
    return ast.TestDecl(ln=tok.ln, col=tok.col, name=name, body=body)


__all__ = ["parse_top_level_item"]
