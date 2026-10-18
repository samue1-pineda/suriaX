"""``function_decl`` (EBNF).

::
    function_decl = "fn" ( IDENTIFIER | DUNDER ) "(" [ param_list ] ")"
                    [ "->" type ] ( block | ";" )
    param_list     = param { "," param }
    param          = type IDENTIFIER

El nombre puede ser ``DUNDER`` (``fn __free__(...)``) ademas de
``IDENTIFIER``: es la forma en la que se declara un *hook* de tipo (ver
``semantic/hooks.py``). El parser NO decide si el nombre es un hook
reconocido -- solo transporta el hecho estructural (``FunctionDecl.dunder``)
para que Semantica lo interprete.

Dos formas relajadas (decision de usuario):

 - **``->`` opcional**: sin anotacion de retorno, la funcion devuelve
   ``void`` (``fn get_char();`` == ``fn get_char() -> void;``). El nodo lleva
   un ``PrimitiveTypeExpr('void')`` sintetico para que las fases posteriores
   no distingan el caso.
 - **prototipo**: un ``;`` en lugar del bloque declara solo la FIRMA, sin
   implementarla (``fn put_char(char c) -> void;``) -- una primitiva que
   aporta el backend / ``#extern``. ``FunctionDecl.body`` queda en ``None``.
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

from ..context import ParserContext
from ..cursor import Cursor, is_reserved_word, reserved_word_error
from .block import parse_block
from .types import parse_type, parse_type_params


def parse_function_decl(cursor: Cursor, ctx: ParserContext,
                        visibility: Optional[str] = None,
                        specifier: Optional[str] = None) -> ast.FunctionDecl:
    """``[visibility] [hook|dunder] "fn" ( IDENTIFIER | DUNDER ) ...``.

    ``visibility``/``specifier`` los pre-consume ``grammar/modifiers.py`` y se
    pasan aqui ya resueltos. Si hay ``specifier`` (``hook``/``dunder``) el
    nombre DEBE tener forma ``__x__`` (token ``DUNDER``): esos especificadores
    solo tienen sentido sobre un metodo especial. Un ``fn __x__`` SIN
    especificador es, deliberadamente, una funcion normal (el usuario puede
    usar ``__`` sin colisionar con el sistema de hooks)."""
    tok = cursor.expect(TokenType.FUNCTION)
    name_tok, dunder = _parse_function_name(cursor)
    if specifier is not None and dunder is None:
        raise ParseError.ExpectedTokenError(
            f"'{specifier}' requiere un nombre con forma '__x__'; "
            f"'{name_tok.lexeme}' no la tiene",
            line=name_tok.ln, column=name_tok.col,
        )
    # 'fn make<T>(...)': los parametros de tipo van pegados al NOMBRE, igual
    # que en 'struct { ... } Vector<T>;'. Aqui no hay ambiguedad con la
    # comparacion —esto es una DECLARACION, no una expresion—, asi que se
    # consumen directamente.
    type_params, type_bounds = parse_type_params(cursor, ctx)
    cursor.expect(TokenType.L_PAREN)
    params = _parse_param_list(cursor, ctx)
    cursor.expect(TokenType.R_PAREN)
    return_type = _parse_return_type(cursor, ctx, tok)
    body = _parse_body_or_prototype(cursor, ctx)
    return ast.FunctionDecl(ln=tok.ln, col=tok.col, name=name_tok.lexeme,
                             params=params, return_type=return_type, body=body,
                             dunder=dunder, specifier=specifier,
                             visibility=visibility, type_params=type_params,
                             type_bounds=type_bounds)


def _parse_return_type(cursor: Cursor, ctx: ParserContext, fn_tok) -> ast.TypeExpr:
    """``[ "->" type ]`` -- sin flecha, retorno ``void`` (nodo sintetico
    ubicado en el ``fn`` para que tenga posicion como cualquier otro tipo)."""
    if cursor.match(TokenType.ARROW):
        return parse_type(cursor, ctx)
    return ast.PrimitiveTypeExpr(ln=fn_tok.ln, col=fn_tok.col, name="void")


def _parse_body_or_prototype(cursor: Cursor, ctx: ParserContext) -> Optional[ast.Block]:
    """``block | ";"`` -- el ``;`` declara un prototipo (cuerpo ``None``)."""
    if cursor.match(TokenType.SEMICOLON):
        return None
    return parse_block(cursor, ctx)  # 'parse_block' ya tolera un ';' final opcional


def parse_lambda_signature(cursor: Cursor, ctx: ParserContext, lambda_tok):
    """``"(" [ param_list ] ")" "->" type`` de una lambda: los parametros
    como los de una ``fn`` y la flecha OBLIGATORIA (sin ella el retorno no
    estaria escrito, y una lambda no tiene otra declaracion donde leerlo)."""
    cursor.expect(TokenType.L_PAREN)
    params = _parse_param_list(cursor, ctx)
    cursor.expect(TokenType.R_PAREN)
    if not cursor.check(TokenType.ARROW):
        got = cursor.peek()
        raise ParseError.ExpectedTokenError(
            "una lambda escribe su tipo de retorno: 'lambda (...) -> R' "
            "('-> void' si no devuelve nada); se encontro "
            f"{got.type.name}",
            line=got.ln, column=got.col,
        )
    cursor.advance()
    return params, parse_type(cursor, ctx)


def _parse_function_name(cursor: Cursor):
    tok = cursor.peek()
    if tok.type is TokenType.DUNDER:
        cursor.advance()
        return tok, tok.value  # 'value' ya es el nombre sin guiones (ver scanners/ident.py)
    if tok.type is TokenType.IDENTIFIER:
        cursor.advance()
        return tok, None
    if is_reserved_word(tok):
        raise reserved_word_error(tok)
    raise ParseError.ExpectedTokenError(
        f"se esperaba el nombre de la funcion (IDENTIFIER o DUNDER), se encontro {tok.type.name}",
        line=tok.ln, column=tok.col,
    )


def _parse_param_list(cursor: Cursor, ctx: ParserContext) -> List[ast.Parameter]:
    params: List[ast.Parameter] = []
    if cursor.check(TokenType.R_PAREN):
        return params
    params.append(_parse_param(cursor, ctx))
    while cursor.match(TokenType.COMMA):
        params.append(_parse_param(cursor, ctx))
    return params


def _parse_param(cursor: Cursor, ctx: ParserContext) -> ast.Parameter:
    type_expr = parse_type(cursor, ctx)
    name_tok = cursor.expect_name()
    return ast.Parameter(ln=type_expr.ln, col=type_expr.col, type=type_expr, name=name_tok.lexeme)


__all__ = ["parse_function_decl", "parse_lambda_signature"]
