"""Las pruebas: ``test`` y ``expect`` (EBNF).

::
    test_decl   = "test" STRING_LIT block
                  [ "errfinally" block ] [ "finally" block ] [ ";" ]
    expect_stmt = "expect" "(" expression ")" ( block | ";" )

Un ``test`` es una declaracion de primer nivel: el runner ejecuta su cuerpo
(``--test``); la compilacion normal solo lo valida. El cuerpo COMPRUEBA con
``expect``: al menos uno (PAR029), o la prueba pasaria sin haber mirado nada.

``expect`` solo vale dentro del cuerpo de un ``test`` (tambien en sus bloques
anidados), como ``break`` solo vale dentro de un bucle: fuera es PAR005. No
vale en las clausulas ``errfinally``/``finally``: esas corren cuando la prueba
ya termino. Su bloque es opcional: lo normal es que el camino de exito sea la
sentencia siguiente.

``errfinally`` corre solo si la prueba fallo; ``finally``, siempre y despues.
De una clausula no se sale con ``return``/``break`` (PAR027), como del
``finally`` de un ``try``.
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


def parse_test_decl(cursor: Cursor, ctx: ParserContext) -> ast.TestDecl:
    tok = cursor.expect(TokenType.TEST)
    name_tok = cursor.expect(TokenType.STRING_LIT)
    name = name_tok.value.flat() if hasattr(name_tok.value, "flat") else str(name_tok.value)

    antes = (ctx.in_test, ctx.expects)
    ctx.in_test, ctx.expects = True, 0
    try:
        body = parse_block(cursor, ctx)
        expects = ctx.expects
    finally:
        ctx.in_test, ctx.expects = antes

    errfinally = _clausula(cursor, ctx, TokenType.ERRFINALLY)
    finally_block = _clausula(cursor, ctx, TokenType.FINALLY)
    if cursor.check(TokenType.ERRFINALLY):
        otra = cursor.peek()
        raise ParseError.InvalidStatementError(
            "'errfinally' va ANTES de 'finally' (y una sola vez): primero lo que "
            "corre solo si la prueba fallo, despues lo que corre siempre",
            line=otra.ln, column=otra.col,
        )
    cursor.match(TokenType.SEMICOLON)  # ';' opcional tras la prueba completa

    if expects == 0:
        # se ANOTA, no se lanza: la prueba esta bien formada y se queda en el
        # arbol; lanzarlo la descartaba entera y dejaba su ';' final suelto
        # (un PAR012 en cascada)
        ctx.errors.append(ParseError.TestWithoutExpectError(
            f"la prueba \"{name}\" no tiene ningun 'expect': no comprueba nada y "
            "pasaria siempre. Escribe al menos un 'expect (condicion);'",
            line=tok.ln, column=tok.col,
        ))
    return ast.TestDecl(ln=tok.ln, col=tok.col, name=name, body=body,
                        errfinally=errfinally, finally_block=finally_block)


def _clausula(cursor: Cursor, ctx: ParserContext, clase: TokenType):
    """El bloque de ``errfinally``/``finally`` si esta, o ``None``. De el no se
    sale con un salto (misma regla que el ``finally`` de un ``try``)."""
    if not cursor.match(clase):
        return None
    ctx.finally_loops.append(ctx.loop_depth)
    try:
        return parse_block(cursor, ctx)
    finally:
        ctx.finally_loops.pop()


def parse_expect_stmt(cursor: Cursor, ctx: ParserContext) -> ast.ExpectStmt:
    tok = cursor.expect(TokenType.EXPECT)
    if not ctx.in_test and ctx.lambda_hides_test:
        # A03: el 'expect' esta escrito dentro de un 'test', pero en una
        # lambda, que es una funcion aparte y corta el 'test' de fuera
        raise ParseError.InvalidStatementError(
            "'expect' dentro de una lambda no llega al 'test' de fuera: la "
            "lambda es una funcion aparte y corta el 'test'. Calcula el "
            "resultado con ella y comprueba fuera ('expect (...)' en el cuerpo "
            "del 'test')",
            line=tok.ln, column=tok.col,
        )
    if not ctx.in_test:
        raise ParseError.InvalidStatementError(
            "'expect' fuera de un 'test': es la comprobacion de una prueba y solo "
            "vale dentro de su cuerpo ('test \"nombre\" { expect (condicion); }')",
            line=tok.ln, column=tok.col,
        )
    cursor.expect(TokenType.L_PAREN)
    desde = cursor.pos
    condition = pratt.parse_expression(cursor, ctx)
    text = _texto(cursor.tokens[desde:cursor.pos])
    cursor.expect(TokenType.R_PAREN)
    ctx.expects += 1
    body = None
    if cursor.check(TokenType.L_BRACE):
        body = parse_block(cursor, ctx)
        cursor.match(TokenType.SEMICOLON)  # ';' opcional tras el bloque
    else:
        cursor.expect(TokenType.SEMICOLON)
    return ast.ExpectStmt(ln=tok.ln, col=tok.col, condition=condition,
                          body=body, text=text)


def _texto(tokens) -> str:
    """La condicion como se escribio, a partir de sus tokens: los que estaban
    pegados siguen pegados y los separados (o en otra linea) quedan con UN
    espacio. Es lo que cita el mensaje de un ``expect`` que falla."""
    partes = []
    anterior = None
    for t in tokens:
        if anterior is not None and (
                t.ln != anterior.ln or t.col > anterior.col + len(anterior.lexeme)):
            partes.append(" ")
        partes.append(t.lexeme)
        anterior = t
    return "".join(partes)


__all__ = ["parse_test_decl", "parse_expect_stmt"]
