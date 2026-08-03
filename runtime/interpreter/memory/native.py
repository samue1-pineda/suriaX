"""Celdas respaldadas por el backend de memoria NATIVO (``memory_c``, C++).

Misma interfaz que la :class:`~.pointer.Cell` de Python pura, pero la LOGICA
(maquina de estados LIVE/MOVED/FREED, move-semantics) corre en C++ vía
pybind11 (ver ``runtime/logic_mem/``). El evaluator no cambia: crea ``Cell`` y
llama ``read``/``write``/``move_out``/``free`` igual — solo que el estado de
memoria vive en el backend agnostico del target, el mismo que usaran la VM y
LLVM/WASM.

Selección (``pointer.py``): nativo si el módulo carga, con override por la
variable de entorno ``SURIAX_NATIVE_MEM`` (``0`` fuerza Python puro, ``1``
exige el nativo). Ante cualquier fallo de carga se cae a Python puro: el
frontend nunca depende de esto y el interprete sigue corriendo.
"""

from __future__ import annotations

from typing import Any, Optional

from ..errors import (
    CorruptMemoryHandleError, DoubleMoveError, UseAfterFreeError,
    UseAfterMoveError,
)
from .pointer import CellState

# --- codigos de estado del core C++ (mem_core.hpp::Status) -> error runtime ---
_OK = 0
# status del core -> fabrica de error de runtime (con nombre/posicion).
_STATUS_ERR = {
    1: UseAfterMoveError,       # USE_AFTER_MOVE
    2: UseAfterFreeError,       # USE_AFTER_FREE
    3: DoubleMoveError,         # DOUBLE_MOVE
    4: UseAfterFreeError,       # DOUBLE_FREE (doble 'free' == use-after-free)
    5: CorruptMemoryHandleError,  # BAD_HANDLE (defensivo: celda inexistente)
}
# codigo del core -> CellState de Python (para reprs y trazas).
_STATE = {0: CellState.LIVE, 1: CellState.MOVED, 2: CellState.FREED}

_MSG = {
    UseAfterMoveError: "se usa después de 'move'",
    UseAfterFreeError: "se accede después de 'free'",
    DoubleMoveError: "ya fue movido",
    CorruptMemoryHandleError: "handle de memoria inválido",
}


def _load():
    """Carga ``memory_c`` vía la API de módulos nativos; ``None`` si no está."""
    from ...cxx_api import api
    module = api.load("memory_c")
    if not hasattr(module, "Memory"):
        raise ImportError("memory_c no expone la clase 'Memory'")
    return module


try:
    _MODULE = _load()
    AVAILABLE = True
except Exception:  # pragma: no cover - entorno sin el .so compilado
    _MODULE = None
    AVAILABLE = False

_manager = None


def manager():
    """Instancia (única por proceso) del backend de memoria nativo."""
    global _manager
    if _manager is None:
        _manager = _MODULE.Memory()
    return _manager


def reset() -> None:
    """Recicla TODAS las celdas del backend. El interprete lo llama al empezar
    cada run: los handles son monotonicos dentro de un run y se reciclan aqui
    entre runs (evita crecimiento entre programas en el mismo proceso)."""
    if _manager is not None:
        _manager.reset()


def stats() -> dict:
    """Introspección (tests/trazas): celdas totales, vivas y externas."""
    m = manager()
    return {"total": m.total(), "live": m.live_count(), "extern": m.extern_count()}


class NativeCell:
    """Celda con nombre respaldada por ``memory_c``. Interfaz idéntica a
    :class:`~.pointer.Cell`; la maquina de estados vive en C++."""

    __slots__ = ("_h", "name")

    def __init__(self, value: Any = None, *, name: str = "?") -> None:
        self.name = name
        self._h = manager().create(value)

    @property
    def value(self) -> Any:
        """Lectura CRUDA (sin chequear estado): reprs/trazas, no una
        instruccion del lenguaje."""
        return manager().peek(self._h)

    @property
    def state(self) -> CellState:
        return _STATE.get(manager().state(self._h), CellState.FREED)

    def read(self, *, ln: int = 0, col: int = 0) -> Any:
        status, value = manager().read(self._h)
        if status != _OK:
            raise self._error(status, ln, col)
        return value

    def write(self, value: Any, *, ln: int = 0, col: int = 0) -> None:
        status = manager().write(self._h, value)
        if status != _OK:
            raise self._error(status, ln, col)

    def move_out(self, *, ln: int = 0, col: int = 0) -> Any:
        status, value = manager().move_out(self._h)
        if status != _OK:
            raise self._error(status, ln, col)
        return value

    def free(self, *, ln: int = 0, col: int = 0) -> None:
        status = manager().free_cell(self._h)
        if status != _OK:
            raise self._error(status, ln, col)

    def _error(self, status: int, ln: int, col: int):
        cls = _STATUS_ERR.get(status, UseAfterFreeError)
        return cls(f"'{self.name}' {_MSG[cls]} (backend nativo)", ln=ln, col=col)


__all__ = ["NativeCell", "AVAILABLE", "manager", "reset", "stats"]
