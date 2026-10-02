"""Manejo de errores por EXCEPCIONES: ``throw``, ``try``/``catch`` (EBNF).

::
    throw_stmt = "throw" expression ";"
    try_stmt   = "try" block { catch_clause } [ "finally" block ]
                 (al menos un catch o el finally)

``throw`` inicia la propagacion de un valor por la pila de llamadas; el
``try`` mas cercano en el camino la intercepta, liga el valor al nombre del
``catch`` y ejecuta su bloque. El binding del ``catch`` vive solo en su
bloque (scope propio, ver ``semantic/scope_resolver``).

El tipo ``error`` (``error T`` / ``error``) se parsea en ``grammar/types.py``
(es una anotacion de tipo, no una sentencia).
"""

from __future__ import annotations

try:
    from include import ast_nodes as ast
    from include.t_types import TokenType
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from t_types import TokenType  # type: ignore

from .. import pratt
from ..context import ParserContext
from ..cursor import Cursor
from .block import parse_block
from .types import parse_type


def parse_throw_stmt(cursor: Cursor, ctx: ParserContext) -> ast.ThrowStmt:
    tok = cursor.expect(TokenType.THROW)
    value = pratt.parse_expression(cursor, ctx)
    cursor.expect(TokenType.SEMICOLON)
    return ast.ThrowStmt(ln=tok.ln, col=tok.col, value=value)


def parse_try_stmt(cursor: Cursor, ctx: ParserContext) -> ast.TryStmt:
    tok = cursor.expect(TokenType.TRY)
    try_block = parse_block(cursor, ctx)
    catches = []
    while cursor.check(TokenType.CATCH):
        catches.append(_parse_catch(cursor, ctx))
    finally_block = None
    if cursor.check(TokenType.FINALLY):
        cursor.expect(TokenType.FINALLY)
        ctx.finally_loops.append(ctx.loop_depth)
        try:
            finally_block = parse_block(cursor, ctx)
        finally:
            ctx.finally_loops.pop()
    if not catches and finally_block is None:
        # un 'try' solo no hace nada: el mensaje es el de siempre (se
        # esperaba el 'catch')
        cursor.expect(TokenType.CATCH)
    cursor.match(TokenType.SEMICOLON)  # ';' opcional tras el 'try' completo
    return ast.TryStmt(ln=tok.ln, col=tok.col, try_block=try_block,
                       catches=catches, finally_block=finally_block)


def _parse_catch(cursor: Cursor, ctx: ParserContext) -> ast.CatchClause:
    """``"catch" "(" [ type ] NAME ")" block``.

    El tipo es OPCIONAL y se decide con un lookahead de un token: si tras el
    '(' hay un nombre seguido del ')' de cierre, ese nombre es el binding
    ('catch (e)'); si hay algo mas, lo primero es un tipo y lo segundo el
    binding ('catch (Fallo e)'). No hace falta retroceder — la unica forma
    ambigua tiene exactamente un token dentro de los parentesis.
    """
    tok = cursor.expect(TokenType.CATCH)
    cursor.expect(TokenType.L_PAREN)
    type_expr = None
    if not _solo_el_nombre(cursor):
        type_expr = parse_type(cursor, ctx)
    name_tok = cursor.expect_name()
    cursor.expect(TokenType.R_PAREN)
    block = parse_block(cursor, ctx)
    return ast.CatchClause(ln=tok.ln, col=tok.col, name=name_tok.lexeme,
                           block=block, type=type_expr)


def _solo_el_nombre(cursor: Cursor) -> bool:
    """¿Dentro de los parentesis hay UN solo nombre? ('catch (e)')"""
    primero = cursor.peek()
    if primero.type is not TokenType.IDENTIFIER and \
            primero.type is not TokenType.DUNDER:
        return False
    return cursor.peek(1).type is TokenType.R_PAREN


__all__ = ["parse_throw_stmt", "parse_try_stmt"]
