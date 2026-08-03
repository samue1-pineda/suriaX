"""Manejo de errores por EXCEPCIONES: ``throw``, ``try``/``catch`` (EBNF secc. 2).

::
    throw_stmt = "throw" expression ";"
    try_stmt   = "try" block "catch" "(" IDENTIFIER ")" block

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


def parse_throw_stmt(cursor: Cursor, ctx: ParserContext) -> ast.ThrowStmt:
    tok = cursor.expect(TokenType.THROW)
    value = pratt.parse_expression(cursor, ctx)
    cursor.expect(TokenType.SEMICOLON)
    return ast.ThrowStmt(ln=tok.ln, col=tok.col, value=value)


def parse_try_stmt(cursor: Cursor, ctx: ParserContext) -> ast.TryStmt:
    tok = cursor.expect(TokenType.TRY)
    try_block = parse_block(cursor, ctx)
    cursor.expect(TokenType.CATCH)
    cursor.expect(TokenType.L_PAREN)
    name_tok = cursor.expect_name()
    cursor.expect(TokenType.R_PAREN)
    catch_block = parse_block(cursor, ctx)
    cursor.match(TokenType.SEMICOLON)  # ';' opcional tras el 'try' completo
    return ast.TryStmt(ln=tok.ln, col=tok.col, try_block=try_block,
                       catch_name=name_tok.lexeme, catch_block=catch_block)


__all__ = ["parse_throw_stmt", "parse_try_stmt"]
