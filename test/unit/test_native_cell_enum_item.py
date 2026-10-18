"""unit/native_cell_enum_item — un ``EnumItem`` sobrevive a una celda NATIVA.

El core C++ (``memory_c``) guarda todo ``int`` de Python como un ``int64_t``
y lo devuelve llano: el item de un enum estilo C perdía su nombre y un
genérico volvía a escribir ``1`` en vez de ``VERDE`` (A08). ``NativeCell``
lo envuelve para que el core lo trate como un objeto opaco.

El módulo nativo no siempre está construido, así que la prueba sustituye el
gestor por uno de Python que IMITA la conversión del core (``to_value`` /
``from_value`` de ``runtime/logic_mem/cxx_entry.cpp``): un ``int`` vuelve
como ``int`` llano, lo demás tal cual.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import helpers  # noqa: E402,F401  (pone la raíz del repo en sys.path)
from runtime.interpreter.memory import native  # noqa: E402
from runtime.interpreter.values import EnumItem  # noqa: E402


class _CoreLikeManager:
    """Lo que hace el core con un valor: ``bool``/``int``/``float`` se
    convierten a su tipo llano; cualquier otro objeto se guarda tal cual."""

    def __init__(self) -> None:
        self.cells = {}

    @staticmethod
    def _convert(value):
        if isinstance(value, bool):
            return bool(value)
        if isinstance(value, int):
            return int(value)
        return value

    def create(self, value):
        handle = len(self.cells) + 1
        self.cells[handle] = self._convert(value)
        return handle

    def read(self, handle):
        return 0, self.cells[handle]

    def peek(self, handle):
        return self.cells[handle]

    def write(self, handle, value):
        self.cells[handle] = self._convert(value)
        return 0

    def move_out(self, handle):
        return 0, self.cells[handle]


def test_native_cell_keeps_the_enum_item_name():
    previous = native._manager
    native._manager = _CoreLikeManager()
    try:
        green = EnumItem(1, "Color", "VERDE")
        cell = native.NativeCell(green, name="c")
        for got in (cell.read(), cell.value):
            assert type(got) is EnumItem and got.variant == "VERDE", got
        cell.write(EnumItem(2, "Color", "AZUL"))
        assert cell.move_out().variant == "AZUL"
        # un int llano sigue siendo un int llano
        plain = native.NativeCell(7, name="n")
        assert type(plain.read()) is int and plain.read() == 7
    finally:
        native._manager = previous
