"""Fuente unica de verdad de la precedencia de operadores infijos.

Cubre exactamente la cadena de precedencia de ``docs/gramar/grammar.ebnf``
(seccion 3), de menor a mayor:

    assignment(=, +=, -=, *=, /=, %=) < or < and < equality(==,!=)
        < comparison(<,<=,>,>=) < term(+,-) < factor(*,/,%)

``unary`` (``not``/``-``/``&``), ``placement`` (``at``) y ``postfix``
(``.``/``()``/``[]``) NO son parte de esta tabla: se resuelven de forma
estructural (recursion right-nested / bucle de encadenamiento) en
``expressions/nud.py`` antes de entrar al bucle binario de ``pratt.py``, ya
que ligan mas fuerte que cualquier operador binario y no admiten mezclarse
por precedencia numerica.

``ASSIGN`` no esta en el EBNF formal como parte de ``expression`` (el EBNF
solo la usa dentro de ``var_decl``), pero la reasignacion (``i = i + 1;``,
``p.x = 3;``) aparece en todos los ejemplos del lenguaje y no tiene otra
regla que la cubra. Se modela aqui como el operador de menor precedencia y
asociativo a la derecha (decision ya tomada en ARQUITECTURA.md secc. 5).
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Dict, Tuple

try:
    from include.t_types import TokenType
except ImportError:  # pragma: no cover - ejecucion directa
    from t_types import TokenType  # type: ignore


class Assoc(Enum):
    LEFT = auto()
    RIGHT = auto()


# TokenType -> (binding_power, asociatividad). Escala con huecos (multiplos de
# 10) para poder insertar niveles nuevos sin renumerar los existentes.
BINDING_POWER: Dict[TokenType, Tuple[int, Assoc]] = {
    TokenType.ASSIGN: (10, Assoc.RIGHT),
    # asignacion COMPUESTA: mismo nivel y misma asociatividad que '='. Es
    # azucar ('n += 2' -> 'n = n + 2'), asi que se desazucara en 'build_led'
    # y no llega al AST.
    TokenType.PLUS_ASSIGN: (10, Assoc.RIGHT),
    TokenType.MINUS_ASSIGN: (10, Assoc.RIGHT),
    TokenType.STAR_ASSIGN: (10, Assoc.RIGHT),
    TokenType.SLASH_ASSIGN: (10, Assoc.RIGHT),
    TokenType.PERCENT_ASSIGN: (10, Assoc.RIGHT),

    TokenType.OR: (20, Assoc.LEFT),

    TokenType.AND: (30, Assoc.LEFT),

    TokenType.EQUAL: (40, Assoc.LEFT),
    TokenType.NOT_EQUAL: (40, Assoc.LEFT),

    TokenType.LESS: (50, Assoc.LEFT),
    TokenType.LESS_EQUAL: (50, Assoc.LEFT),
    TokenType.GREATER: (50, Assoc.LEFT),
    TokenType.GREATER_EQUAL: (50, Assoc.LEFT),

    TokenType.PLUS: (60, Assoc.LEFT),
    TokenType.MINUS: (60, Assoc.LEFT),

    TokenType.MULTIPLY: (70, Assoc.LEFT),
    TokenType.DIVIDE: (70, Assoc.LEFT),
    TokenType.MODULO: (70, Assoc.LEFT),
}


def next_min_bp(bp: int, assoc: Assoc) -> int:
    """Binding power minimo para el operando derecho de un operador infijo.

    Izquierda-asociativo: +1 evita que el mismo nivel se anide a la derecha
    (fuerza left-fold). Derecha-asociativo (``=``): se mantiene igual, para
    que ``a = b = c`` anide como ``a = (b = c)``.
    """
    return bp + 1 if assoc is Assoc.LEFT else bp


__all__ = ["Assoc", "BINDING_POWER", "next_min_bp"]
