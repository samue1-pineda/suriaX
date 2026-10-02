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
    desplazamiento.
    """
    tok = cursor.peek()
    if tok.type is TokenType.GREATER:
        sig = cursor.peek(1)
        if sig.ln == tok.ln and sig.col == tok.col + 1:
            if sig.type is TokenType.GREATER:
                return Token(TokenType.SHIFT_RIGHT, ">>", ">>", tok.ln, tok.col), 2
            if sig.type is TokenType.GREATER_EQUAL:
                return Token(TokenType.SHIFT_RIGHT_ASSIGN, ">>=", ">>=", tok.ln, tok.col), 2
    return tok, 1


__all__ = ["parse_expression"]
