"""``block = "{" { statement } "}"`` -- compartido por ``fn``, ``if``/``else``,
``while``, ``region`` y los cuerpos de ``case`` con llaves.

Politica de ``;`` tolerante (decision de usuario, ver ARQUITECTURA.md): el
EBNF formal no exige ``;`` tras un ``block``, pero los ejemplos del lenguaje
la escriben de forma consistente tras CADA ``}`` de estas construcciones. En
lugar de repartir ``cursor.match(SEMICOLON)`` por cada sitio que llama a
``parse_block`` (fn, if, while, region, case-arm), se consume aqui una sola
vez: un ``block`` que se cierra puede ir seguido de un ``;`` opcional, sin
costo extra mas alla de un ``match`` O(1).
"""

from __future__ import annotations

try:
    from include import ast_nodes as ast
    from include.t_types import TokenType
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from t_types import TokenType  # type: ignore

from ..context import ParserContext
from ..cursor import Cursor


def parse_block(cursor: Cursor, ctx: ParserContext, *,
                trailing_semicolon: bool = True) -> ast.Block:
    """``trailing_semicolon=False``: el bloque es el cuerpo de una EXPRESION
    (una lambda) y el ``;`` que lo siga es de la sentencia que la contiene."""
    open_tok = cursor.expect(TokenType.L_BRACE)

    from .statements import parse_statement  # import diferido: rompe el ciclo block<->statements
    statements = []
    while not cursor.check(TokenType.R_BRACE) and not cursor.at_end():
        statements.append(parse_statement(cursor, ctx))

    cursor.expect(TokenType.R_BRACE)
    if trailing_semicolon:
        cursor.match(TokenType.SEMICOLON)  # ';' opcional tras '}' (superset tolerante)
    return ast.Block(ln=open_tok.ln, col=open_tok.col, statements=statements)


__all__ = ["parse_block"]
