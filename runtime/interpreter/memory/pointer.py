"""Celdas y punteros: las INSTRUCCIONES DE MEMORIA del runtime (secc. 8.2/8.3).

Todo binding vive en una :class:`Cell` (por eso ``&x`` puede producir un
:class:`Pointer` estable). La celda es la única dueña del ESTADO de memoria:

    LIVE  -> legible/escribible
    MOVED -> su valor fue transferido con ``move`` (leerla: RT001;
             volver a moverla: RT002)
    FREED -> liberada con ``free`` (cualquier acceso: RT003)

La Semántica ya rechazó estáticamente lo que pudo (SEM004/SEM005, SEM015);
aquí se hace cumplir el resto EN EJECUCIÓN — los caminos por ramas que el
análisis lineal conservador deja pasar a propósito (``memory_check``,
falsos negativos documentados). El intérprete no re-chequea lo ya validado:
p. ej. la escritura a través de ``ptr`` no-mutable (SEM015) no se re-verifica.

No hay arenas por región: el modelo se retiró en v0.2.0. Las arenas del
modelo nuevo son un tipo de librería y se apoyan en estas mismas celdas.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Any, Optional

from ..errors import (
    DoubleMoveError, UseAfterFreeError, UseAfterMoveError,
)


class CellState(Enum):
    LIVE = auto()
    MOVED = auto()
    FREED = auto()


class PyCell:
    """Una ubicación de memoria con nombre (variable, parámetro o campo).

    Implementación en Python PURA. El backend por defecto es el NATIVO
    (``memory_c``, C++); esta clase es el *fallback* portátil cuando el .so no
    está compilado para el intérprete actual (ver ``Cell`` al final del módulo
    y ``memory/native.py``). Ambos comparten esta interfaz exacta."""

    __slots__ = ("value", "state", "name", "released")

    def __init__(self, value: Any = None, *, name: str = "?") -> None:
        self.value = value
        self.state = CellState.LIVE
        self.name = name
        #: la liberó '__release__' al soltar SU BLOQUE (no un 'free' del
        #: programa): cambia el mensaje, ver 'freed_message'
        self.released = False

    # ------------------------------------------------------------------ #
    # accesos con verificación de estado (la instrucción, no el azúcar)
    # ------------------------------------------------------------------ #
    def read(self, *, ln: int = 0, col: int = 0) -> Any:
        if self.state is CellState.MOVED:
            raise UseAfterMoveError(
                f"'{self.name}' se usa después de 'move' (detectado en runtime)",
                ln=ln, col=col,
            )
        if self.state is CellState.FREED:
            raise UseAfterFreeError(
                freed_message(self, "se usa"), ln=ln, col=col,
            )
        return self.value

    def write(self, value: Any, *, ln: int = 0, col: int = 0) -> None:
        if self.state is CellState.FREED:
            raise UseAfterFreeError(
                freed_message(self, "se escribe"), ln=ln, col=col,
            )
        # escribir REVIVE una celda movida: un valor nuevo no está movido
        # (misma regla que memory_check aplica estáticamente al reasignar).
        self.value = value
        self.state = CellState.LIVE

    def move_out(self, *, ln: int = 0, col: int = 0) -> Any:
        """``move x``: transfiere el valor e INVALIDA la celda."""
        if self.state is CellState.MOVED:
            raise DoubleMoveError(
                f"'{self.name}' ya fue movido", ln=ln, col=col,
            )
        if self.state is CellState.FREED:
            raise UseAfterFreeError(
                f"'move' sobre '{self.name}' ya liberado", ln=ln, col=col,
            )
        value = self.value
        self.value = None
        self.state = CellState.MOVED
        return value

    def free(self, *, ln: int = 0, col: int = 0) -> None:
        """``free``: marca la celda como liberada (todo acceso posterior —
        directo o a través de un puntero — es RT003)."""
        if self.state is CellState.FREED:
            raise UseAfterFreeError(
                f"doble 'free' sobre '{self.name}'", ln=ln, col=col,
            )
        self.value = None
        self.state = CellState.FREED


class Pointer:
    """Valor puntero: referencia a una :class:`Cell` + permiso de escritura.

    ``mut`` refleja el tipo estático (``ptr mutable T`` vs ``ptr T``); viaja
    para la traza educativa y el differential testing — la Semántica ya
    impidió escrituras ilegales, el runtime no las re-verifica.
    """

    __slots__ = ("cell", "mut", "target")

    def __init__(self, cell: Cell, *, mut: bool, target: Any = None) -> None:
        self.cell = cell
        self.mut = mut
        #: el OBJETO prestado, en el préstamo de un elemento de un bloque
        #: (``&b[i]``, lo que devuelven ``Vector.at``/``at_mut``); ``None`` en
        #: el de una variable o un campo. Ver :meth:`deref`.
        self.target = target

    def deref(self, *, ln: int = 0, col: int = 0) -> Any:
        """El valor apuntado, comprobando que el préstamo siga vivo.

        El préstamo de un ELEMENTO presta ese elemento, no la celda: si el
        contenedor lo reemplaza (``set``, ``v[i] = x``) o lo saca y corre los
        demás (``take``), la celda tiene OTRO objeto, y leerlo por el
        préstamo viejo era leer un elemento que el programa nunca prestó.
        La VM lo dice (RT003: el objeto prestado murió) y aquí también. El de
        una variable sí sigue a la celda: ``p = &x; x = 5`` lee 5, como en C.
        """
        value = self.cell.read(ln=ln, col=col)
        if self.target is not None and value is not self.target:
            raise UseAfterFreeError(
                f"el elemento prestado ('{self.cell.name}') ya no existe: el "
                "contenedor lo reemplazó o lo sacó (por ejemplo con 'set', "
                "'take' o 'pop'), y el préstamo murió con él. Pide el "
                "préstamo justo antes de usarlo",
                ln=ln, col=col)
        return value

    def __repr__(self) -> str:  # para f-strings / trazas
        flag = " mutable" if self.mut else ""
        return f"<ptr{flag} -> {self.cell.name} ({self.cell.state.name.lower()})>"


def freed_message(cell: Any, action: str) -> str:
    """El mensaje de un acceso a una celda LIBERADA.

    Si la liberó ``__release__`` al soltar su BLOQUE, la causa no es un
    ``free`` del programa: el contenedor dueño del bloque REUBICÓ su
    almacenamiento (un vector que creció reserva otro bloque, mueve los
    elementos y suelta el viejo) o murió. Decir "después de 'free'" mandaba
    a buscar un ``free`` que no existe."""
    if getattr(cell, "released", False):
        return (f"'{cell.name}' {action} después de que su contenedor "
                "reubicara su almacenamiento (creció y movió los elementos a "
                "otro bloque) o muriera: un préstamo de un elemento ('at', "
                "'at_mut', 'data') no sobrevive a eso")
    return f"'{cell.name}' {action} después de 'free'"


def _select_cell():
    """Elige el backend de memoria: NATIVO (``memory_c``) por defecto; Python
    puro si el .so no carga. ``SURIAX_NATIVE_MEM`` fuerza uno u otro
    (``0`` = Python, ``1`` = nativo obligatorio)."""
    import os
    pref = os.environ.get("SURIAX_NATIVE_MEM")
    if pref == "0":
        return PyCell
    from . import native  # import diferido: rompe el ciclo con este modulo
    if pref == "1" and not native.AVAILABLE:
        raise RuntimeError(
            "SURIAX_NATIVE_MEM=1 pero el backend nativo 'memory_c' no cargó "
            f"({native.LOAD_ERROR}). Compílalo con el intérprete actual: "
            "cmake -S . -B build && cmake --build build --target suriax-native"
        )
    return native.NativeCell if native.AVAILABLE else PyCell


#: la celda EFECTIVA que usa el intérprete (nativa o Python, ver _select_cell).
Cell = _select_cell()


__all__ = ["Cell", "PyCell", "CellState", "Pointer", "freed_message"]
