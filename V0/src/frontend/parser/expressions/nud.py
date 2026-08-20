"""Handlers de la posicion PREFIJO de una expresion.

Implementa la cadena estructural completa
``unary -> placement -> postfix -> primary`` de ``docs/gramar/grammar.ebnf``
(seccion 3). Estos niveles NO se resuelven por binding power (a diferencia de
los operadores binarios de ``precedence.py``): el EBNF los define como
niveles fijos anidados a la derecha, asi que se implementan como funciones
que se llaman entre si.

``PRIMARY_HANDLERS`` es la tabla de despacho ``TokenType -> constructor``
para la regla ``primary``: agregar una forma primaria nueva es agregar una
entrada aqui, sin tocar ``parse_unary``/``parse_postfix``.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from contextlib import contextmanager
from typing import Callable, Dict, List, Union

try:
    from include import ast_nodes as ast
    from include.t_types import Interp, StringValue, Token, TokenType
    from error_handler import ParseError
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from t_types import Interp, StringValue, Token, TokenType  # type: ignore
    import ParseError  # type: ignore

from ..context import ParserContext
from ..cursor import Cursor

# --- prefijos unarios: 'unary = ( "not" | "-" | "&" ) unary | placement' ---
# '&' construye su nodo propio (AddrOf): las reglas de punteros (lvalue,
# mutabilidad heredada) son semantica de ese nodo, no de un operador generico.
_UNARY_OPS: Dict[TokenType, str] = {
    TokenType.NOT: "not",
    TokenType.MINUS: "-",
}


def parse_unary(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    tok = cursor.peek()
    if tok.type is TokenType.ADDRESS:
        cursor.advance()
        operand = parse_unary(cursor, ctx)
        return ast.AddrOf(ln=tok.ln, col=tok.col, operand=operand)
    operator = _UNARY_OPS.get(tok.type)
    if operator is not None:
        cursor.advance()
        operand = parse_unary(cursor, ctx)  # right-recursivo: '- - x' es valido
        return ast.UnaryOp(ln=tok.ln, col=tok.col, operator=operator, operand=operand)
    return parse_postfix(cursor, ctx)


def parse_postfix(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    """``postfix = ( primary | struct_literal ) { "." IDENTIFIER | "(" [arg_list] ")" | "[" expression "]" }``."""
    expr = parse_primary(cursor, ctx)
    # 'dotted' acumula el nombre mientras la expresion siga siendo un NOMBRE
    # puro ('Nodo', 'point.Point'); pasa a None en cuanto aparece una llamada
    # o una indexacion, porque entonces ya no nombra un tipo.
    dotted = expr.name if expr.__class__ is ast.Identifier else None
    while True:
        tok = cursor.peek()
        # struct_literal = IDENTIFIER { "." IDENTIFIER } "{" [ field_init... ] "}"
        # solo tras un nombre NOMINAL, desnudo ('Nodo{ v: 1 }') o cualificado
        # por su modulo ('point.Point{ x: 1 }' — un struct publicado por una
        # libreria se nombra igual en una anotacion que en un literal). No hay
        # ambiguedad con bloques (las condiciones van entre parentesis, un
        # bloque es statement, nunca sigue a un nombre en posicion de expresion).
        if tok.type is TokenType.L_BRACE and dotted is not None \
                and not ctx.no_struct_literal:
            expr = _struct_literal(cursor, ctx, expr, dotted)
            dotted = None
        elif tok.type is TokenType.LESS and dotted is not None \
                and not ctx.no_struct_literal:
            # posible literal de un GENERICO ('Caja<int>{ v: 1 }'). Es la
            # unica posicion del lenguaje donde '<' es ambiguo (comparacion
            # vs argumentos de tipo), y se resuelve MIRANDO: solo son
            # argumentos si tras el '>' viene un '{'. Si no, se retrocede y
            # el '<' vuelve a ser el operador que siempre fue.
            type_args = _type_args_de_literal(cursor, ctx)
            if type_args is None:
                return expr
            expr = _struct_literal(cursor, ctx, expr, dotted, type_args)
            dotted = None
        elif tok.type is TokenType.DOT:
            cursor.advance()
            member_tok = cursor.expect_name()
            expr = ast.MemberAccess(ln=expr.ln, col=expr.col, obj=expr, member=member_tok.lexeme)
            if dotted is not None:
                dotted = f"{dotted}.{member_tok.lexeme}"
        elif tok.type is TokenType.L_PAREN:
            cursor.advance()
            args = _parse_arg_list(cursor, ctx)
            cursor.expect(TokenType.R_PAREN)
            expr = ast.Call(ln=expr.ln, col=expr.col, callee=expr, args=args)
            dotted = None
        elif tok.type is TokenType.L_BRACKET:
            cursor.advance()
            from .. import pratt  # import diferido: 'pratt' importa este modulo
            with _struct_literals_allowed(ctx):
                index_expr = pratt.parse_expression(cursor, ctx)
            cursor.expect(TokenType.R_BRACKET)
            expr = ast.Index(ln=expr.ln, col=expr.col, obj=expr, index=index_expr)
            dotted = None
        else:
            return expr


def _type_args_de_literal(cursor: Cursor, ctx: ParserContext):
    """``"<" type { "," type } ">"`` SI y solo si le sigue un ``"{"``.

    Devuelve los argumentos, o ``None`` si lo que hay no es esa forma — en
    cuyo caso el cursor queda EXACTAMENTE donde estaba y el ``<`` lo recoge
    el motor Pratt como comparacion. Es el unico retroceso del parser, y
    esta acotado: nunca cruza el ``>``, y ningun error llega a ``ctx``
    porque ``parse_type_args`` senala lanzando, no registrando.
    """
    inicio = cursor.pos
    from ..grammar.types import parse_type_args
    try:
        args = parse_type_args(cursor, ctx)
    except ParseError.ParseError:
        cursor.pos = inicio
        return None
    if not cursor.check(TokenType.L_BRACE):
        cursor.pos = inicio
        return None
    return args


def _struct_literal(cursor: Cursor, ctx: ParserContext,
                    name_expr: ast.Expression, type_name: str,
                    type_args=None) -> ast.Expression:
    """``IDENTIFIER { "." IDENTIFIER } [ type_args ] "{" [ IDENTIFIER ":" expression { "," ... } ] "}"``.

    Instancia un struct nominal (``type_name`` es el tipo, ya sea desnudo o
    cualificado por su modulo). Coma final tolerada; campos en el orden
    escrito."""
    cursor.expect(TokenType.L_BRACE)
    from .. import pratt
    names: List[str] = []
    values: List[ast.Expression] = []
    with _struct_literals_allowed(ctx):
        while not cursor.check(TokenType.R_BRACE) and not cursor.at_end():
            name_tok = cursor.expect_name()
            cursor.expect(TokenType.COLON)
            names.append(name_tok.lexeme)
            values.append(pratt.parse_expression(cursor, ctx))
            if not cursor.match(TokenType.COMMA):
                break
    cursor.expect(TokenType.R_BRACE)
    return ast.StructLiteral(ln=name_expr.ln, col=name_expr.col,
                             type_name=type_name, field_names=names,
                             values=values, type_args=type_args or [])


@contextmanager
def _struct_literals_allowed(ctx: ParserContext):
    """Dentro de un DELIMITADOR (``(...)``, ``[...]``, ``{campo: ...}``) un
    literal de struct vuelve a ser valido aunque el contexto exterior lo
    haya suprimido: en ``case f(Nodo{ v: 1 })`` el '{' del argumento no es
    el cuerpo de la rama. Sin esto, la marca de ``ctx.no_struct_literal``
    se filtraria hacia dentro de las subexpresiones."""
    previous = ctx.no_struct_literal
    ctx.no_struct_literal = False
    try:
        yield
    finally:
        ctx.no_struct_literal = previous


def _parse_arg_list(cursor: Cursor, ctx: ParserContext) -> List[ast.Expression]:
    """``arg_list = expression { "," expression }``."""
    args: List[ast.Expression] = []
    if cursor.check(TokenType.R_PAREN):
        return args
    from .. import pratt
    with _struct_literals_allowed(ctx):
        args.append(pratt.parse_expression(cursor, ctx))
        while cursor.match(TokenType.COMMA):
            args.append(pratt.parse_expression(cursor, ctx))
    return args


def parse_primary(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    tok = cursor.peek()
    handler = PRIMARY_HANDLERS.get(tok.type)
    if handler is None:
        raise ParseError.InvalidExpressionError(
            f"token inesperado en expresion: {tok.type.name}",
            line=tok.ln, column=tok.col,
        )
    return handler(cursor, ctx)


# ----------------------------------------------------------------------------
# handlers 'primary' individuales
# ----------------------------------------------------------------------------

def _identifier(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    tok = cursor.advance()
    return ast.Identifier(ln=tok.ln, col=tok.col, name=tok.lexeme)


def _lit_int(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    tok = cursor.advance()
    return ast.Literal(ln=tok.ln, col=tok.col, value=tok.value, literal_kind="int")


def _lit_float(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    tok = cursor.advance()
    return ast.Literal(ln=tok.ln, col=tok.col, value=tok.value, literal_kind="float")


def _lit_char(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    tok = cursor.advance()
    return ast.Literal(ln=tok.ln, col=tok.col, value=tok.value, literal_kind="char")


def _lit_true(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    tok = cursor.advance()
    return ast.Literal(ln=tok.ln, col=tok.col, value=True, literal_kind="bool")


def _lit_false(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    tok = cursor.advance()
    return ast.Literal(ln=tok.ln, col=tok.col, value=False, literal_kind="bool")


def _lit_null(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    tok = cursor.advance()
    return ast.Literal(ln=tok.ln, col=tok.col, value=None, literal_kind="null")


def _lit_string(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    """Camino rapido sin interpolacion -> ``Literal``; con interpolacion ->
    ``InterpolatedString`` con cada ``{expr}`` ya analizado (ver ``_parse_interp``)."""
    tok = cursor.advance()
    sv: StringValue = tok.value
    if not sv.is_interpolated:
        return ast.Literal(ln=tok.ln, col=tok.col, value=sv.flat(), literal_kind="str")

    parts: List[Union[str, ast.Expression]] = []
    for part in sv.parts:
        parts.append(part if isinstance(part, str) else _parse_interp(part, tok))
    return ast.InterpolatedString(ln=tok.ln, col=tok.col, parts=parts)


def _parse_interp(interp: Interp, string_tok: Token) -> ast.Expression:
    """Analiza el texto crudo de un ``{expr}`` como una expresion completa.

    El lexer solo delimita el texto de la interpolacion (ver ``Interp`` en
    ``t_types.py``); su analisis es responsabilidad del parser (EBNF secc. 5).
    Se re-tokeniza y re-parsea el fragmento de forma aislada (una interpolacion
    nunca cruza saltos de linea, ver ``scanners/strings.py``), y las posiciones
    del sub-arbol resultante se reubican a la posicion real en el archivo.
    """
    from src.frontend.lexer.lexer import tokenize as _tokenize

    sub_tokens = _tokenize(interp.expr)
    sub_cursor = Cursor(sub_tokens)
    sub_ctx = ParserContext()

    from .. import pratt
    try:
        expr = pratt.parse_expression(sub_cursor, sub_ctx)
    except ParseError.ParseError as exc:
        raise ParseError.InvalidExpressionError(
            f"interpolacion invalida: {exc.message}",
            line=string_tok.ln, column=interp.col,
        ) from exc
    if not sub_cursor.at_end():
        raise ParseError.InvalidExpressionError(
            "la interpolacion contiene mas de una expresion",
            line=string_tok.ln, column=interp.col,
        )

    _relocate(expr, string_tok.ln, interp.col)
    return expr


def _relocate(node: object, ln: int, col: int) -> None:
    """Reescribe ``ln``/``col`` de todo el sub-arbol a la posicion real en el
    archivo (el mini-lex de una interpolacion cuenta desde 1:1)."""
    if isinstance(node, ast.ASTNode):
        node.ln = ln
        node.col = col
    if is_dataclass(node):
        for f in fields(node):
            _relocate(getattr(node, f.name), ln, col)
    elif isinstance(node, (list, tuple)):
        for item in node:
            _relocate(item, ln, col)


def _grouping(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    """``"(" expression ")"`` -- no genera nodo propio, devuelve la interna."""
    cursor.expect(TokenType.L_PAREN)
    from .. import pratt
    with _struct_literals_allowed(ctx):
        expr = pratt.parse_expression(cursor, ctx)
    cursor.expect(TokenType.R_PAREN)
    return expr


def _sizeof(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    tok = cursor.expect(TokenType.SIZEOF)
    cursor.expect(TokenType.L_PAREN)
    from ..grammar.types import parse_type
    type_expr = parse_type(cursor, ctx)
    cursor.expect(TokenType.R_PAREN)
    return ast.SizeofExpr(ln=tok.ln, col=tok.col, type=type_expr)


def _cast(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    """``"cast" type_args "(" expression ")"`` -- exactamente UN argumento de
    tipo (``cast<int8>(x)``); la posicion ``<...>`` es la regla compartida
    ``grammar/types.parse_type_args`` (los genericos de libreria la reusaran)."""
    tok = cursor.expect(TokenType.CAST)
    from ..grammar.types import parse_type_args
    type_args = parse_type_args(cursor, ctx)
    if len(type_args) != 1:
        raise ParseError.InvalidExpressionError(
            f"'cast' toma exactamente un argumento de tipo, recibe {len(type_args)}",
            line=tok.ln, column=tok.col,
        )
    cursor.expect(TokenType.L_PAREN)
    from .. import pratt
    value = pratt.parse_expression(cursor, ctx)
    cursor.expect(TokenType.R_PAREN)
    return ast.CastExpr(ln=tok.ln, col=tok.col, type=type_args[0], value=value)


PRIMARY_HANDLERS: Dict[TokenType, Callable[[Cursor, ParserContext], ast.Expression]] = {
    TokenType.IDENTIFIER: _identifier,
    TokenType.DUNDER: _identifier,  # referencia a un nombre '__x__' (p. ej. llamar un hook explicitamente)
    TokenType.INT_LIT: _lit_int,
    TokenType.FLOAT_LIT: _lit_float,
    TokenType.CHAR_LIT: _lit_char,
    TokenType.STRING_LIT: _lit_string,
    TokenType.TRUE: _lit_true,
    TokenType.FALSE: _lit_false,
    TokenType.NULL: _lit_null,
    TokenType.L_PAREN: _grouping,
    TokenType.SIZEOF: _sizeof,
    TokenType.CAST: _cast,
    # 'make' vuelve a ser un IDENTIFIER corriente.
}


__all__ = [
    "parse_unary", "parse_postfix", "parse_primary",
    "PRIMARY_HANDLERS",
]
