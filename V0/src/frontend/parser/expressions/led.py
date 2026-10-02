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
    TokenType.MODULO: "%",
    TokenType.PIPE: "|",
    TokenType.CARET: "^",
    TokenType.ADDRESS: "&",
    TokenType.SHIFT_LEFT: "<<",
    TokenType.SHIFT_RIGHT: ">>",
}

# asignacion COMPUESTA -> el operador binario que la expande. Es azucar: no
# hay nodo AST propio, 'n += 2' se construye como 'n = n + 2'.
_COMPOUND_OPS: Dict[TokenType, str] = {
    TokenType.PLUS_ASSIGN: "+",
    TokenType.MINUS_ASSIGN: "-",
    TokenType.STAR_ASSIGN: "*",
    TokenType.SLASH_ASSIGN: "/",
    TokenType.PERCENT_ASSIGN: "%",
    TokenType.AMP_ASSIGN: "&",
    TokenType.PIPE_ASSIGN: "|",
    TokenType.CARET_ASSIGN: "^",
    TokenType.SHIFT_LEFT_ASSIGN: "<<",
    TokenType.SHIFT_RIGHT_ASSIGN: ">>",
}

# lvalues validos para el lado izquierdo de 'target = value'
_LVALUE_TYPES = (ast.Identifier, ast.MemberAccess, ast.Index)


def build_led(op_tok: Token, left: ast.Expression, right: ast.Expression) -> ast.Expression:
    if op_tok.type is TokenType.ASSIGN:
        _exigir_lvalue(op_tok, left, "'='")
        return ast.Assignment(ln=left.ln, col=left.col, target=left, value=right)

    compuesto = _COMPOUND_OPS.get(op_tok.type)
    if compuesto is not None:
        return expandir_compuesta(op_tok, left, right, compuesto)

    operator = _BINARY_OPS[op_tok.type]
    return ast.BinaryOp(ln=left.ln, col=left.col, operator=operator, left=left, right=right)


def expandir_compuesta(op_tok: Token, left: ast.Expression,
                       right: ast.Expression, operador: str) -> ast.Expression:
    """``x op= v`` -> ``x = x op v``. Tambien expande ``x++`` (con ``v`` = 1).

    Azucar PURO del parser: no hay nodo propio, asi que ni la Semantica, ni el
    HIR, ni el interprete se enteran de que existe.

    El destino aparece DOS veces en el arbol resultante, asi que solo se
    admite un destino cuya evaluacion se pueda repetir sin cambiar nada
    (:func:`_repetible`). ``v[f()] += 1`` llamaria a ``f`` dos veces, y eso no
    es lo que nadie escribe queriendo; se rechaza diciendo como escribirlo.
    """
    _exigir_lvalue(op_tok, left, f"'{op_tok.lexeme}'")
    if not _repetible(left):
        raise ParseError.InvalidExpressionError(
            f"'{op_tok.lexeme}' necesita un destino que se pueda evaluar dos "
            "veces sin efectos: este tiene una llamada dentro. Escribelo "
            "completo ('x = x " + operador + " ...') para que quede claro "
            "cuantas veces se evalua",
            line=op_tok.ln, column=op_tok.col,
        )
    valor = ast.BinaryOp(ln=left.ln, col=left.col, operator=operador,
                         left=_copiar(left), right=right)
    return ast.Assignment(ln=left.ln, col=left.col, target=left, value=valor,
                          azucar=f"'{op_tok.lexeme}': x = x {operador} "
                                 + ("1" if op_tok.lexeme in ("++", "--") else "..."))


def _exigir_lvalue(op_tok: Token, left: ast.Expression, cual: str) -> None:
    if not isinstance(left, _LVALUE_TYPES):
        raise ParseError.InvalidExpressionError(
            f"el lado izquierdo de {cual} no es asignable",
            line=op_tok.ln, column=op_tok.col,
        )


def _repetible(expr: ast.Expression) -> bool:
    """¿Evaluar ``expr`` dos veces da lo mismo y no hace nada mas?

    Un nombre, un campo de algo repetible, o un indice repetible sobre algo
    repetible. Cualquier llamada rompe la propiedad.
    """
    if isinstance(expr, ast.Identifier):
        return True
    if isinstance(expr, ast.MemberAccess):
        return _repetible(expr.obj)
    if isinstance(expr, ast.Index):
        return _repetible(expr.obj) and (
            isinstance(expr.index, ast.Literal) or _repetible(expr.index))
    return False


def _copiar(expr: ast.Expression) -> ast.Expression:
    """Copia del destino para la lectura de la expansion.

    Se COPIA en vez de compartir el mismo objeto porque las fases siguientes
    anotan el arbol EN SITIO (``restype``, dueños, drops): dos posiciones
    distintas del arbol apuntando al mismo nodo se anotarian la una a la otra.
    Solo cubre las formas que :func:`_repetible` deja pasar.
    """
    if isinstance(expr, ast.Identifier):
        return ast.Identifier(ln=expr.ln, col=expr.col, name=expr.name)
    if isinstance(expr, ast.MemberAccess):
        return ast.MemberAccess(ln=expr.ln, col=expr.col,
                                obj=_copiar(expr.obj), member=expr.member)
    if isinstance(expr, ast.Index):
        indice = (ast.Literal(ln=expr.index.ln, col=expr.index.col,
                              value=expr.index.value,
                              literal_kind=expr.index.literal_kind)
                  if isinstance(expr.index, ast.Literal)
                  else _copiar(expr.index))
        return ast.Index(ln=expr.ln, col=expr.col, obj=_copiar(expr.obj),
                         index=indice)
    raise AssertionError("destino no repetible: _repetible tenia que haberlo filtrado")


__all__ = ["build_led", "expandir_compuesta"]
