"""``struct_decl`` (EBNF). Nombre AL FINAL (estilo C):

::
    struct_decl = "struct" "{" { field } "}" IDENTIFIER ";"
    field       = type IDENTIFIER ";"
"""

from __future__ import annotations

from typing import List, Optional

try:
    from include import ast_nodes as ast
    from include.t_types import TokenType
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from t_types import TokenType  # type: ignore

from ..context import ParserContext
from ..cursor import Cursor
from .types import parse_type, parse_type_params


def parse_struct_decl(cursor: Cursor, ctx: ParserContext,
                      visibility: Optional[str] = None) -> ast.StructDecl:
    tok = cursor.expect(TokenType.STRUCT)
    cursor.expect(TokenType.L_BRACE)

    fields: List[ast.Field] = []
    while not cursor.check(TokenType.R_BRACE) and not cursor.at_end():
        fields.append(_parse_field(cursor, ctx))

    cursor.expect(TokenType.R_BRACE)
    name_tok = cursor.expect_name()
    params, bounds = parse_type_params(cursor, ctx)
    cursor.expect(TokenType.SEMICOLON)
    return ast.StructDecl(ln=tok.ln, col=tok.col, fields=fields,
                          name=name_tok.lexeme, visibility=visibility,
                          type_params=params, type_bounds=bounds)


def _parse_field(cursor: Cursor, ctx: ParserContext) -> ast.Field:
    type_expr = parse_type(cursor, ctx)
    name_tok = cursor.expect_name()
    cursor.expect(TokenType.SEMICOLON)
    return ast.Field(ln=type_expr.ln, col=type_expr.col, type=type_expr, name=name_tok.lexeme)


__all__ = ["parse_struct_decl"]
