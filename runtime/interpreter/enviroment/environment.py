"""Environment de ejecución: cadena de frames ``nombre -> Cell`` (secc. 6).

Un frame por scope léxico ejecutándose (función, bloque). La resolución
camina la cadena hacia el padre — espejo dinámico de la cadena de ``Scope``
que la Semántica ya validó, así que un nombre no encontrado aquí es una
BRECHA del análisis estático (``RT006``), no un error esperable del usuario.

Sin cierres (closures) en el lenguaje: el frame raíz de una llamada apunta
directo a los GLOBALES de su unidad, no al frame del llamador.
"""

from __future__ import annotations

from typing import Optional

from ..errors import UndefinedNameError
from ..memory.pointer import Cell


class Frame:
    __slots__ = ("cells", "parent", "lanzados")

    def __init__(self, parent: Optional["Frame"] = None) -> None:
        self.cells: dict[str, Cell] = {}
        self.parent = parent
        #: solo en el marco de un 'catch': nombre del binding -> la clave del
        #: tipo con el que LLEGÓ el valor. Un 'catch (e)' no sabe al compilar
        #: qué atrapó, así que 'throw e;' la recupera de aquí (ver
        #: 'Evaluator._stmt_throw'). None en cualquier otro marco.
        self.lanzados: Optional[dict] = None

    def lanzado(self, name: str):
        """La clave de tipo con la que llegó el binding ``name`` de un
        ``catch``, o None si ``name`` no es un binding de ``catch``."""
        frame: Optional[Frame] = self
        while frame is not None:
            if name in frame.cells:
                return frame.lanzados.get(name) if frame.lanzados else None
            frame = frame.parent
        return None

    def define(self, name: str, cell: Cell) -> None:
        # el shadowing por frame es legal (la Semántica ya validó duplicados
        # DENTRO de un mismo scope); el último define de este frame gana.
        self.cells[name] = cell

    def lookup(self, name: str, *, ln: int = 0, col: int = 0) -> Cell:
        frame: Optional[Frame] = self
        while frame is not None:
            cell = frame.cells.get(name)
            if cell is not None:
                return cell
            frame = frame.parent
        raise UndefinedNameError(
            f"'{name}' no está ligado en runtime (brecha del análisis estático)",
            ln=ln, col=col,
        )

    def try_lookup(self, name: str) -> Optional[Cell]:
        frame: Optional[Frame] = self
        while frame is not None:
            cell = frame.cells.get(name)
            if cell is not None:
                return cell
            frame = frame.parent
        return None


__all__ = ["Frame"]
