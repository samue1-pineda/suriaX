"""Punto unico de acceso a las tablas de despacho de expresiones.

``PRIMARY_HANDLERS`` (``TokenType -> constructor`` de la regla ``primary``)
vive en ``nud.py``; el binding power de los operadores binarios vive en
``precedence.py``. Este modulo los reune para que ``pratt.py`` dependa de un
solo import al construir el motor.
"""

from __future__ import annotations

from ..precedence import BINDING_POWER, Assoc, next_min_bp
from .led import build_led
from .nud import PRIMARY_HANDLERS, parse_unary

__all__ = ["PRIMARY_HANDLERS", "BINDING_POWER", "Assoc", "next_min_bp", "build_led", "parse_unary"]
