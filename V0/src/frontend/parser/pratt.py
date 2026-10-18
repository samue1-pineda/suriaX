"""Motor Pratt: bucle de precedencia binaria sobre ``expressions/``.

Punto de entrada UNICO para cualquier expresion en todo el parser
(``grammar/`` lo llama para ``var_decl``, ``return``, argumentos,
condiciones, etc.). Agnostico de que token concreto representa cada
operador: consulta ``expressions/registry.py`` para el binding power y para
la cadena prefija (``nud``), y delega la construccion de nodos infijos a
``expressions/led.py``.

Complejidad: O(n) en el numero de tokens de la expresion -- cada token se
consume una vez (``cursor.advance``); no hay backtracking (ver
ARQUITECTURA.md secc. 1).
"""

from __future__ import annotations

try:
    from error_handler import ParseError
except ImportError:  # pragma: no cover - ejecucion directa
    import ParseError  # type: ignore
from .context import ParserContext
from include.t_types import Token, TokenType
from .cursor import Cursor
from .expressions.registry import BINDING_POWER, build_led, next_min_bp, parse_unary

try:
    from include import ast_nodes as ast
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore


def parse_expression(cursor: Cursor, ctx: ParserContext, min_bp: int = 0) -> ast.Expression:
    """``expression = logic_or`` (mas ``assignment``, ver ``precedence.py``).

    ``min_bp`` es el binding power minimo que un operador infijo debe superar
    para seguir extendiendo la expresion actual (precedence climbing).
    """
    left = parse_unary(cursor, ctx)

    while True:
        op_tok, ocupa = _operador(cursor)
        prec = BINDING_POWER.get(op_tok.type)
        if prec is None:
            return left
        bp, assoc = prec
        if bp < min_bp:
            return left

        for _ in range(ocupa):
            cursor.advance()
        right = parse_expression(cursor, ctx, next_min_bp(bp, assoc))
        left = build_led(op_tok, left, right)


def _operador(cursor: Cursor):
    """El operador infijo en el cursor y cuántos tokens ocupa.

    ``>>`` y ``>>=`` no los emite el lexer (ver ``SHIFT_RIGHT``): son un ``>``
    seguido PEGADO de ``>`` o de ``>=``. Si hay un espacio en medio no son un
    desplazamiento. ``??`` igual (ver ``NULL_COALESCE``): dos ``?`` pegados;
    un ``?`` suelto en posicion de operador no es nada y termina la
    expresion.
    """
    tok = cursor.peek()
    if tok.type is TokenType.NULLABLE:
        sig = cursor.peek(1)
        if sig.type is TokenType.NULLABLE and sig.ln == tok.ln \
                and sig.col == tok.col + 1:
            return Token(TokenType.NULL_COALESCE, "??", "??", tok.ln, tok.col), 2
        if _looks_like_ternary(cursor):
            _foreign_operator(tok, "?")
    if tok.type in (TokenType.ADDRESS, TokenType.PIPE):
        sig = cursor.peek(1)
        if sig.type is tok.type and sig.ln == tok.ln \
                and sig.col == tok.col + 1:
            _foreign_operator(tok, tok.lexeme * 2)
    if tok.type is TokenType.GREATER:
        sig = cursor.peek(1)
        if sig.ln == tok.ln and sig.col == tok.col + 1:
            if sig.type is TokenType.GREATER:
                return Token(TokenType.SHIFT_RIGHT, ">>", ">>", tok.ln, tok.col), 2
            if sig.type is TokenType.GREATER_EQUAL:
                return Token(TokenType.SHIFT_RIGHT_ASSIGN, ">>=", ">>=", tok.ln, tok.col), 2
    return tok, 1


#: operadores de OTROS lenguajes -> lo que se escribe en suriaX (H06)
_FOREIGN_OPERATORS = {
    "?": ("el operador ternario 'c ? a : b' no existe en suriaX: usa "
          "'if (c) { ... } else { ... }'"),
    "&&": "'&&' no existe en suriaX: el 'y' logico es 'and' ('a and b')",
    "||": "'||' no existe en suriaX: el 'o' logico es 'or' ('a or b')",
}


#: donde termina, como muy tarde, la expresion que contiene el '?'
_TERNARY_STOPS = frozenset({TokenType.SEMICOLON, TokenType.L_BRACE,
                            TokenType.R_BRACE, TokenType.EOF})


def _looks_like_ternary(cursor: Cursor) -> bool:
    """¿El ``?`` suelto del cursor tiene un ``:`` detras, al mismo nivel de
    parentesis y antes del fin de la sentencia (``c ? a : b``)? Solo
    entonces la pista del ternario es cierta; un ``?`` sin ``:`` (``a ? 0``)
    sigue siendo el PAR003 de siempre. Solo mira hacia delante, no consume."""
    depth = 0
    offset = 1
    while True:
        kind = cursor.peek(offset).type
        if kind in _TERNARY_STOPS:
            return False
        if kind in (TokenType.L_PAREN, TokenType.L_BRACKET):
            depth += 1
        elif kind in (TokenType.R_PAREN, TokenType.R_BRACKET):
            if depth == 0:
                return False
            depth -= 1
        elif kind is TokenType.COLON and depth == 0:
            return True
        offset += 1


def _foreign_operator(tok: Token, written: str) -> None:
    """PAR012 con la pista de suriaX ante un operador de otro lenguaje en
    posicion de operador: el ternario (un ``?`` suelto; ``??`` si existe),
    ``&&`` y ``||`` (dos tokens PEGADOS: ``a & &b`` con espacio sigue siendo
    un 'y' de bits con una direccion). Antes eran un PAR003 que nombraba un
    token interno ("se encontro NULLABLE"), un AST006 que leia ``b && n``
    como ``b & (&n)`` y un PAR012 "PIPE", sin pista (H06). Igual que PAR023
    con ``var x = 3``."""
    raise ParseError.InvalidExpressionError(
        _FOREIGN_OPERATORS[written], line=tok.ln, column=tok.col)


__all__ = ["parse_expression"]
