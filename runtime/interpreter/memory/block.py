"""Bloque de memoria: N celdas contiguas (base de los vectores).

Lo que ``__reserve__`` entrega y lo que la indexación ``buf[i]`` recorre. Es
la contraparte de :class:`~.pointer.Cell` para las estructuras dinámicas: un
:class:`Cell` es UNA ubicación con nombre; un :class:`Block` es un tramo de
ubicaciones consecutivas, cada una su propia celda (así ``&buf[i]``, la
escritura por índice y el estado move/free siguen viviendo en la celda, sin
casos especiales en el evaluator).

Es DELIBERADAMENTE mínimo: reservar, indexar y copiar. No hay realloc, ni
crecer en sitio, ni layout por bytes — eso lo aporta una librería de vector
ENCIMA de estas primitivas (``lib/mem`` + ``__reserve__``/``__copy__``), y el
layout real de memoria es cosa del backend/MIR, no del tree-walk. El
intérprete solo necesita que las celdas existan y sean direccionables.
"""

from __future__ import annotations

from typing import Any

from ..errors import IndexOutOfRangeError
from .pointer import Cell


class Block:
    """Tramo de ``size`` celdas contiguas, todas LIVE con valor ``null``."""

    __slots__ = ("cells",)

    def __init__(self, size: int) -> None:
        # una Cell por elemento: el índice hace de nombre para trazas/errores.
        self.cells = [Cell(None, name=f"[{i}]") for i in range(size)]

    def __len__(self) -> int:
        return len(self.cells)

    def element(self, index: int, *, ln: int = 0, col: int = 0) -> Cell:
        """Celda del elemento ``index`` (verificando los límites: RT013)."""
        if not isinstance(index, int) or isinstance(index, bool) \
                or index < 0 or index >= len(self.cells):
            raise IndexOutOfRangeError(
                f"índice {index!r} fuera de rango [0, {len(self.cells)})",
                ln=ln, col=col,
            )
        return self.cells[index]

    def __repr__(self) -> str:  # trazas / format_value
        return f"<block[{len(self.cells)}]>"


__all__ = ["Block"]
