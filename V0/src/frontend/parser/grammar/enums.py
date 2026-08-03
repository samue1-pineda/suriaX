"""``enum_decl`` (EBNF secc. 1, tipos compuestos):

::
    enum_decl = "enum" IDENTIFIER "{" enum_item { "," enum_item } [ "," ] "}"
    enum_item = IDENTIFIER [ "=" expression ]

``;`` final: **obligatorio** (decision explicita de usuario -- a diferencia
de ``fn``/``if``/``while``/``region``/``match``, que la toleran opcional,
ver ``grammar/block.py``).
"""

from __future__ import annotations

from typing import List, Optional

try:
    from include import ast_nodes as ast
    from include.t_types import TokenType
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from t_types import TokenType  # type: ignore

from .. import pratt
from ..context import ParserContext
from ..cursor import Cursor


def parse_enum_decl(cursor: Cursor, ctx: ParserContext,
                    visibility: Optional[str] = None) -> ast.EnumDecl:
    tok = cursor.expect(TokenType.ENUM)
    name_tok = cursor.expect_name()
    cursor.expect(TokenType.L_BRACE)

    items: List[ast.EnumItem] = []
    if not cursor.check(TokenType.R_BRACE):
        items.append(_parse_enum_item(cursor, ctx))
        while cursor.match(TokenType.COMMA):
            if cursor.check(TokenType.R_BRACE):  # coma final opcional
                break
            items.append(_parse_enum_item(cursor, ctx))

    cursor.expect(TokenType.R_BRACE)
    cursor.expect(TokenType.SEMICOLON)  # obligatorio
    return ast.EnumDecl(ln=tok.ln, col=tok.col, name=name_tok.lexeme,
                        items=items, visibility=visibility)


def _parse_enum_item(cursor: Cursor, ctx: ParserContext) -> ast.EnumItem:
    name_tok = cursor.expect_name()
    value = None
    if cursor.match(TokenType.ASSIGN):
        value = pratt.parse_expression(cursor, ctx)
    return ast.EnumItem(ln=name_tok.ln, col=name_tok.col, name=name_tok.lexeme, value=value)


__all__ = ["parse_enum_decl"]
