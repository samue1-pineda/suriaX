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
        op_tok = cursor.peek()
        prec = BINDING_POWER.get(op_tok.type)
        if prec is None:
            return left
        bp, assoc = prec
        if bp < min_bp:
            return left

        cursor.advance()
        right = parse_expression(cursor, ctx, next_min_bp(bp, assoc))
        left = build_led(op_tok, left, right)


__all__ = ["parse_expression"]
