"""Modelo de memoria en runtime (secc. 8): celdas, punteros, move y free.

Solo :mod:`pointer`: no hay arenas aquí. El modelo por regiones se retiró en
v0.2.0 y las arenas del modelo nuevo son un TIPO DE LIBRERÍA, no una
construcción del intérprete — no necesitan un módulo propio.
"""

from .pointer import Cell, CellState, Pointer

__all__ = ["Cell", "CellState", "Pointer"]
