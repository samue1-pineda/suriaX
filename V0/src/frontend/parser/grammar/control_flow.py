"""Control de flujo: ``if``/``else``, ``while``, ``match``/``case``,
``return``, ``break``, ``continue`` (EBNF secc. 2).

::
    if_stmt    = "if" "(" expression ")" block [ "else" ( block | if_stmt ) ]
    while_stmt = "while" "(" expression ")" block
    match_stmt = "match" "(" expression ")" "{" { case_arm } "}"
    case_arm   = "case" expression ":" ( statement | block )
    return_stmt   = "return" [ expression ] ";"
    break_stmt    = "break" ";"
    continue_stmt = "continue" ";"

``case_arm``: el EBNF exige ``":"`` siempre, pero en el corpus real
(docs/examples/structs_and_control.md) el ``:`` se omite cuando la rama es un
bloque con llaves (``case X { ... };``) y solo aparece antes de una sentencia
suelta (``case X: stmt;``). Se implementa esa forma tolerante: ``:``
obligatorio unicamente cuando NO sigue un ``{``.
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

from .. import pratt
from ..context import ParserContext
from ..cursor import Cursor
from .block import parse_block


def parse_if_stmt(cursor: Cursor, ctx: ParserContext) -> ast.IfStmt:
    tok = cursor.expect(TokenType.IF)
    cursor.expect(TokenType.L_PAREN)
    condition = pratt.parse_expression(cursor, ctx)
    cursor.expect(TokenType.R_PAREN)
    then_block = parse_block(cursor, ctx)

    else_branch = None
    if cursor.match(TokenType.ELSE):
        if cursor.check(TokenType.IF):
            else_branch = parse_if_stmt(cursor, ctx)
        else:
            else_branch = parse_block(cursor, ctx)

    return ast.IfStmt(ln=tok.ln, col=tok.col, condition=condition,
                       then_block=then_block, else_branch=else_branch)


def parse_while_stmt(cursor: Cursor, ctx: ParserContext) -> ast.WhileStmt:
    tok = cursor.expect(TokenType.WHILE)
    cursor.expect(TokenType.L_PAREN)
    condition = pratt.parse_expression(cursor, ctx)
    cursor.expect(TokenType.R_PAREN)
    ctx.enter_loop()
    try:
        body = parse_block(cursor, ctx)
    finally:
        ctx.exit_loop()
    return ast.WhileStmt(ln=tok.ln, col=tok.col, condition=condition, body=body)


def parse_match_stmt(cursor: Cursor, ctx: ParserContext) -> ast.MatchStmt:
    tok = cursor.expect(TokenType.MATCH)
    cursor.expect(TokenType.L_PAREN)
    subject = pratt.parse_expression(cursor, ctx)
    cursor.expect(TokenType.R_PAREN)
    cursor.expect(TokenType.L_BRACE)

    cases = []
    while cursor.check(TokenType.CASE):
        cases.append(_parse_case_arm(cursor, ctx))

    cursor.expect(TokenType.R_BRACE)
    cursor.match(TokenType.SEMICOLON)  # ';' opcional tras el 'match' completo
    return ast.MatchStmt(ln=tok.ln, col=tok.col, subject=subject, cases=cases)


def _parse_case_arm(cursor: Cursor, ctx: ParserContext) -> ast.CaseArm:
    tok = cursor.expect(TokenType.CASE)
    # el '{' que puede seguir al patron abre el CUERPO de la rama, no un
    # literal de struct ('case Origen { ... }', EBNF 'case_arm'): sin esta
    # marca la expresion del patron se lo comeria y el 'case' siguiente
    # fallaria pidiendo ':'.
    previous = ctx.no_struct_literal
    ctx.no_struct_literal = True
    try:
        pattern = pratt.parse_expression(cursor, ctx)
    finally:
        ctx.no_struct_literal = previous

    # el ':' es obligatorio solo cuando el cuerpo NO es un bloque; cuando SI
    # lo es, se admiten las dos formas ('case X { }' y la costumbre de C,
    # 'case X: { }'). Un bloque no es un 'statement' de la gramatica, asi que
    # sin este caso el ':{' caia en 'parse_expression' y el diagnostico
    # ('token inesperado en expresion: L_BRACE') no decia nada del 'case'.
    if cursor.check(TokenType.COLON) \
            and cursor.peek(1).type is TokenType.L_BRACE:
        cursor.advance()
    if cursor.check(TokenType.L_BRACE):
        body: ast.Statement = parse_block(cursor, ctx)
    else:
        cursor.expect(TokenType.COLON)
        from .statements import parse_statement  # import diferido: rompe el ciclo con statements
        body = parse_statement(cursor, ctx)

    return ast.CaseArm(ln=tok.ln, col=tok.col, pattern=pattern, body=body)


def parse_return_stmt(cursor: Cursor, ctx: ParserContext) -> ast.ReturnStmt:
    tok = cursor.expect(TokenType.RETURN)
    value = None
    if not cursor.check(TokenType.SEMICOLON):
        value = pratt.parse_expression(cursor, ctx)
    cursor.expect(TokenType.SEMICOLON)
    return ast.ReturnStmt(ln=tok.ln, col=tok.col, value=value)


def parse_break_stmt(cursor: Cursor, ctx: ParserContext) -> ast.BreakStmt:
    tok = cursor.expect(TokenType.BREAK)
    if not ctx.in_loop():
        raise ParseError.InvalidStatementError(
            "'break' fuera de un bucle", line=tok.ln, column=tok.col,
        )
    cursor.expect(TokenType.SEMICOLON)
    return ast.BreakStmt(ln=tok.ln, col=tok.col)


def parse_continue_stmt(cursor: Cursor, ctx: ParserContext) -> ast.ContinueStmt:
    tok = cursor.expect(TokenType.CONTINUE)
    if not ctx.in_loop():
        raise ParseError.InvalidStatementError(
            "'continue' fuera de un bucle", line=tok.ln, column=tok.col,
        )
    cursor.expect(TokenType.SEMICOLON)
    return ast.ContinueStmt(ln=tok.ln, col=tok.col)


__all__ = [
    "parse_if_stmt", "parse_while_stmt", "parse_match_stmt",
    "parse_return_stmt", "parse_break_stmt", "parse_continue_stmt",
]
