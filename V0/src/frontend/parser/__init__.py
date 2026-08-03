"""API publica del paquete ``parser``.

Expone :func:`parse`: el resto del compilador (fases futuras: Semantica,
HIR) no debe conocer el cursor, el motor Pratt ni como esta organizada la
gramatica interna -- solo esta funcion y el AST que devuelve.
"""

from __future__ import annotations

from typing import List, Tuple

try:
    from include import ast_nodes as ast
    from include.t_types import Token
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from t_types import Token  # type: ignore

from .parser import Parser


def parse(tokens: List[Token]) -> Tuple[ast.Program, list]:
    """Analiza ``tokens`` (ya producidos por el ``Lexer``).

    Devuelve ``(programa, errores)``: ``errores`` es la lista de
    ``ParseError`` recuperados en modo panico (ver ``recovery.py``); el AST
    devuelto es el mejor esfuerzo posible incluso si hubo errores.
    """
    parser = Parser(tokens)
    program = parser.parse()
    return program, parser.ctx.errors


__all__ = ["parse", "Parser"]
