"""Construccion de nodos INFIJOS (la mitad ``led`` del bucle de ``pratt.py``).

Dado un operador ya consumido y sus dos operandos (izquierdo ya resuelto,
derecho recien parseado por el propio motor), arma el nodo AST
correspondiente. ``ASSIGN`` es el unico caso especial: valida que el operando
izquierdo sea un lvalue antes de construir la asignacion.
"""

from __future__ import annotations

from typing import Dict

try:
    from include import ast_nodes as ast
    from include.t_types import Token, TokenType
    from error_handler import ParseError
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from t_types import Token, TokenType  # type: ignore
    import ParseError  # type: ignore

_BINARY_OPS: Dict[TokenType, str] = {
    TokenType.OR: "or",
    TokenType.AND: "and",
    TokenType.EQUAL: "==",
    TokenType.NOT_EQUAL: "!=",
    TokenType.LESS: "<",
    TokenType.LESS_EQUAL: "<=",
    TokenType.GREATER: ">",
    TokenType.GREATER_EQUAL: ">=",
    TokenType.PLUS: "+",
    TokenType.MINUS: "-",
    TokenType.MULTIPLY: "*",
    TokenType.DIVIDE: "/",
}

# lvalues validos para el lado izquierdo de 'target = value'
_LVALUE_TYPES = (ast.Identifier, ast.MemberAccess, ast.Index)


def build_led(op_tok: Token, left: ast.Expression, right: ast.Expression) -> ast.Expression:
    if op_tok.type is TokenType.ASSIGN:
        if not isinstance(left, _LVALUE_TYPES):
            raise ParseError.InvalidExpressionError(
                "el lado izquierdo de '=' no es asignable",
                line=op_tok.ln, column=op_tok.col,
            )
        return ast.Assignment(ln=left.ln, col=left.col, target=left, value=right)

    operator = _BINARY_OPS[op_tok.type]
    return ast.BinaryOp(ln=left.ln, col=left.col, operator=operator, left=left, right=right)


__all__ = ["build_led"]
