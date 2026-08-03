"""Modelo de memoria en runtime (secc. 8): celdas, punteros, move y free.

v1: solo :mod:`pointer` (RBMM/arenas por región llega con la versión del
esquema HIR que las transporte — ``region.py`` vive en el plan, no aquí).
"""

from .pointer import Cell, CellState, Pointer

__all__ = ["Cell", "CellState", "Pointer"]
