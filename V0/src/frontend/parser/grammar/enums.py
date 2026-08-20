"""``enum_decl`` (EBNF secc. 1, tipos compuestos):

::
    enum_decl = "enum" IDENTIFIER "{" enum_item { "," enum_item } [ "," ] "}"
    enum_item = IDENTIFIER ( "(" type { "," type } ")" | [ "=" expression ] )

La forma con parentesis es una variante con PAYLOAD ('Literal(int)'): el
enum deja de ser un conjunto de enteros con nombre y pasa a ser un tipo
SUMA. Ver ``ast_nodes.EnumDecl.es_suma``.

``;`` final: **obligatorio** (decision explicita de usuario -- a diferencia
de ``fn``/``if``/``while``/``region``/``match``, que la toleran opcional,
ver ``grammar/block.py``).
"""

from __future__ import annotations

from typing import List, Optional

try:
    from include import ast_nodes as ast
    from include.t_types import TokenType
    from error_handler import ParseError
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from t_types import TokenType  # type: ignore
    import ParseError  # type: ignore

from .. import pratt
from ..context import ParserContext
from ..cursor import Cursor
from .types import parse_type


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

    # variante con PAYLOAD: 'Literal(int)', 'Suma(Nodo ptr, Nodo ptr)'. Los
    # parentesis tras el nombre no pueden ser otra cosa aqui (una variante no
    # es una llamada), asi que no hay ambiguedad que resolver.
    if cursor.check(TokenType.L_PAREN):
        cursor.advance()
        payload = [parse_type(cursor, ctx)]
        while cursor.match(TokenType.COMMA):
            if cursor.check(TokenType.R_PAREN):  # coma final tolerada
                break
            payload.append(parse_type(cursor, ctx))
        cursor.expect(TokenType.R_PAREN)
        if cursor.check(TokenType.ASSIGN):
            tok = cursor.peek()
            raise ParseError.InvalidStatementError(
                f"la variante '{name_tok.lexeme}' lleva payload, asi que no "
                "tiene un valor entero que fijar: el '=' de un enum numera "
                "variantes UNIDAD",
                line=tok.ln, column=tok.col,
            )
        return ast.EnumItem(ln=name_tok.ln, col=name_tok.col,
                            name=name_tok.lexeme, payload=payload)

    value = None
    if cursor.match(TokenType.ASSIGN):
        value = pratt.parse_expression(cursor, ctx)
    return ast.EnumItem(ln=name_tok.ln, col=name_tok.col, name=name_tok.lexeme, value=value)


__all__ = ["parse_enum_decl"]
