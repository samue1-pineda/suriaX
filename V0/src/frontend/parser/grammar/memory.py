"""Modelo de memoria: *region-based + move-semantics* (EBNF secc. 2).

::
    region_stmt   = region_mods "region" IDENTIFIER block
    region_mods   = { "shrd" | "mutable" | "na" }        (orden libre, sin repetir)
    new_stmt      = "new" "(" region_mods "region" IDENTIFIER ")" ";"
    delete_stmt   = "delete" "(" [ "region" IDENTIFIER ] ")" ";"
    in_region_stmt= "in" "region" IDENTIFIER ( ":" statement | block )
    move_stmt     = "move" ( expression | "region" IDENTIFIER "->" "region" IDENTIFIER ) ";"
    free_stmt     = "free" expression ";"

Los tres modificadores de region son componibles y de ORDEN LIBRE
(``shrd mutable na region r`` es valido). El parser solo transporta los flags;
la ejecucion REAL del modelo RBMM la hace el runtime de forma AGNOSTICA DEL
TARGET (el interprete llama a la implementacion C++ via pybind11), NO se difiere
al MIR ni se simula.

``make`` NO esta aqui: es una EXPRESION (regla ``primary``) y vive en
``expressions/nud.py``. Ver ARQUITECTURA.md secc. 5.
"""

from __future__ import annotations

from typing import Tuple

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
from .block import parse_block

# modificadores validos de una region (orden libre entre ellos).
_REGION_MODS = frozenset({TokenType.SHRD, TokenType.MUTABLE, TokenType.NA})


def starts_region(cursor: Cursor) -> bool:
    """¿La posicion actual arranca una declaracion de region? Lookahead puro:
    salta los modificadores (``shrd``/``mutable``/``na``, cualquier orden) y
    verifica que sigue ``region``. Usado por el dispatch de ``statements.py``
    para desambiguar ``mutable region r`` del mal uso de ``mutable``."""
    offset = 0
    while cursor.peek(offset).type in _REGION_MODS:
        offset += 1
    return cursor.peek(offset).type is TokenType.REGION


def _parse_region_modifiers(cursor: Cursor) -> Tuple[bool, bool, bool]:
    """Consume ``{ shrd | mutable | na }`` en cualquier orden. Devuelve
    ``(shared, mutable, na)``. Repetir un modificador es un error dirigido."""
    shared = mutable = na = False
    while True:
        tok = cursor.peek()
        if tok.type is TokenType.SHRD:
            shared = _set_once(shared, "shrd", tok)
        elif tok.type is TokenType.MUTABLE:
            mutable = _set_once(mutable, "mutable", tok)
        elif tok.type is TokenType.NA:
            na = _set_once(na, "na", tok)
        else:
            break
        cursor.advance()
    return shared, mutable, na


def _set_once(already: bool, name: str, tok) -> bool:
    if already:
        raise ParseError.InvalidStatementError(
            f"modificador de region '{name}' repetido", line=tok.ln, column=tok.col,
        )
    return True


def parse_region_stmt(cursor: Cursor, ctx: ParserContext) -> ast.RegionStmt:
    """``region_mods "region" IDENTIFIER block`` -- forma con BLOQUE."""
    start = cursor.peek()
    shared, mutable, na = _parse_region_modifiers(cursor)
    cursor.expect(TokenType.REGION)
    name_tok = cursor.expect_name()
    ctx.enter_region()
    try:
        body = parse_block(cursor, ctx)
    finally:
        ctx.exit_region()
    return ast.RegionStmt(ln=start.ln, col=start.col, name=name_tok.lexeme,
                          body=body, shared=shared, mutable=mutable, na=na)


def parse_new_stmt(cursor: Cursor, ctx: ParserContext) -> ast.NewStmt:
    """``"new" "(" region_mods "region" IDENTIFIER ")" ";"`` -- inicializa una
    region como handle (sin bloque). Modelo hibrido: su vida es manual."""
    tok = cursor.expect(TokenType.NEW)
    cursor.expect(TokenType.L_PAREN)
    shared, mutable, na = _parse_region_modifiers(cursor)
    cursor.expect(TokenType.REGION)
    name_tok = cursor.expect_name()
    cursor.expect(TokenType.R_PAREN)
    cursor.expect(TokenType.SEMICOLON)
    return ast.NewStmt(ln=tok.ln, col=tok.col, name=name_tok.lexeme,
                       shared=shared, mutable=mutable, na=na)


def parse_delete_stmt(cursor: Cursor, ctx: ParserContext) -> ast.DeleteStmt:
    """``"delete" "(" [ "region" IDENTIFIER ] ")" ";"``.

    Forma externa ``delete(region r)`` (nombra la region) o forma interna
    ``delete()`` (sin argumento: la region que encierra el ``delete``, se
    resuelve en la Semantica)."""
    tok = cursor.expect(TokenType.DELETE)
    cursor.expect(TokenType.L_PAREN)
    name = None
    if not cursor.check(TokenType.R_PAREN):
        cursor.expect(TokenType.REGION)
        name = cursor.expect_name().lexeme
    cursor.expect(TokenType.R_PAREN)
    cursor.expect(TokenType.SEMICOLON)
    return ast.DeleteStmt(ln=tok.ln, col=tok.col, name=name)


def parse_in_region_stmt(cursor: Cursor, ctx: ParserContext) -> ast.InRegionStmt:
    """``"in" "region" IDENTIFIER ( block | ":" statement )`` -- operaciones EN
    el contexto de una region. Forma con ``{ }`` para varias sentencias, forma
    corta ``:`` para una sola (espeja ``case_arm``)."""
    tok = cursor.expect(TokenType.IN)
    cursor.expect(TokenType.REGION)
    name_tok = cursor.expect_name()
    if cursor.check(TokenType.L_BRACE):
        body: ast.Statement = parse_block(cursor, ctx)
    else:
        cursor.expect(TokenType.COLON)
        from .statements import parse_statement  # import diferido: rompe el ciclo
        body = parse_statement(cursor, ctx)
    return ast.InRegionStmt(ln=tok.ln, col=tok.col, region=name_tok.lexeme, body=body)


def parse_move_stmt(cursor: Cursor, ctx: ParserContext) -> ast.Statement:
    """``"move" ( "region" IDENTIFIER "->" "region" IDENTIFIER | expression ) ";"``.

    ``move region a -> region b`` transfiere una region (``MoveRegionStmt``);
    en cualquier otro caso es el move de un valor (``MoveStmt``). Se distingue
    con UN token de lookahead (``region`` tras ``move``)."""
    tok = cursor.expect(TokenType.MOVE)
    if cursor.check(TokenType.REGION):
        cursor.advance()
        src = cursor.expect_name().lexeme
        cursor.expect(TokenType.ARROW)
        cursor.expect(TokenType.REGION)
        dst = cursor.expect_name().lexeme
        cursor.expect(TokenType.SEMICOLON)
        return ast.MoveRegionStmt(ln=tok.ln, col=tok.col, src=src, dst=dst)
    target = pratt.parse_expression(cursor, ctx)
    cursor.expect(TokenType.SEMICOLON)
    return ast.MoveStmt(ln=tok.ln, col=tok.col, target=target)


def parse_free_stmt(cursor: Cursor, ctx: ParserContext) -> ast.FreeStmt:
    tok = cursor.expect(TokenType.FREE)
    target = pratt.parse_expression(cursor, ctx)
    cursor.expect(TokenType.SEMICOLON)
    return ast.FreeStmt(ln=tok.ln, col=tok.col, target=target)


__all__ = [
    "parse_region_stmt", "parse_new_stmt", "parse_delete_stmt",
    "parse_in_region_stmt", "parse_move_stmt", "parse_free_stmt",
    "starts_region",
]
