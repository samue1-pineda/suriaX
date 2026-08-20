"""Modelo de memoria: *ownership + move-semantics* (EBNF secc. 2).

::
    move_stmt = "move" expression ";"
    free_stmt = "free" expression ";"

Son las dos unicas sentencias del modelo de memoria. `move` transfiere la
propiedad de un valor (el origen queda invalido) y `free` destruye antes de
que el ambito se cierre; la destruccion por defecto ocurre al cerrar el
ambito y no tiene sintaxis.

Las construcciones del modelo por REGIONES (`region`, `shrd`/`na`,
`new`/`delete`, `in region`, `move region a -> region b`, `make T in r`,
`x at r`) se retiraron en v0.2.0 junto con el modelo; el razonamiento esta en
``documentation/source/memory_decision.rst``. Sus palabras dejaron de estar
reservadas, asi que hoy son identificadores corrientes.
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


def parse_move_stmt(cursor: Cursor, ctx: ParserContext) -> ast.MoveStmt:
    """``"move" expression ";"`` -- transferencia de propiedad."""
    tok = cursor.expect(TokenType.MOVE)
    target = pratt.parse_expression(cursor, ctx)
    cursor.expect(TokenType.SEMICOLON)
    return ast.MoveStmt(ln=tok.ln, col=tok.col, target=target)


def parse_free_stmt(cursor: Cursor, ctx: ParserContext) -> ast.FreeStmt:
    """``"free" expression ";"`` -- destruccion anticipada."""
    tok = cursor.expect(TokenType.FREE)
    target = pratt.parse_expression(cursor, ctx)
    cursor.expect(TokenType.SEMICOLON)
    return ast.FreeStmt(ln=tok.ln, col=tok.col, target=target)


__all__ = ["parse_move_stmt", "parse_free_stmt"]
