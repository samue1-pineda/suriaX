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


#: Por qué NO cargó el módulo nativo (``None`` si cargó). La caída a Python
#: puro es deliberada, pero el motivo no se tira: sin él, "no cargó" podía ser
#: que nadie lo construyó, que se construyó para otra versión de Python o que
#: el ``.so`` está roto, y cada caso se arregla distinto.
LOAD_ERROR: Optional[str] = None

try:
    _MODULE = _load()
    AVAILABLE = True
except Exception as exc:  # noqa: BLE001 - se recupera, pero conserva la causa
    _MODULE = None
    AVAILABLE = False
    LOAD_ERROR = f"{type(exc).__name__}: {exc}"

_manager = None


class _TaggedItem:
    """Un :class:`~..values.EnumItem` (el entero de un enum estilo C que
    sabe su nombre) dentro de una celda NATIVA.

    El core C++ guarda todo ``int`` de Python como un ``int64_t`` y lo
    devuelve como un ``int`` llano: el nombre se perdía en silencio y un
    genérico volvía a escribir ``1`` en vez de ``VERDE`` (A08). Envuelto,
    el core lo trata como cualquier objeto opaco (``T_EXTERN``) y vuelve
    intacto. Solo existe entre ``_box`` y ``_unbox``."""

    __slots__ = ("item",)

    def __init__(self, item) -> None:
        self.item = item


def _box(value: Any) -> Any:
    """Lo que se entrega al core: un ``EnumItem`` envuelto, lo demás igual."""
    from ..values import EnumItem
    return _TaggedItem(value) if isinstance(value, EnumItem) else value


def _unbox(value: Any) -> Any:
    return value.item if type(value) is _TaggedItem else value


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

    __slots__ = ("_h", "name", "released")

    def __init__(self, value: Any = None, *, name: str = "?") -> None:
        self.name = name
        self._h = manager().create(_box(value))
        #: la liberó '__release__' con su bloque (ver pointer.freed_message)
        self.released = False

    @property
    def value(self) -> Any:
        """Lectura CRUDA (sin chequear estado): reprs/trazas, no una
        instruccion del lenguaje."""
        return _unbox(manager().peek(self._h))

    @property
    def state(self) -> CellState:
        return _STATE.get(manager().state(self._h), CellState.FREED)

    def read(self, *, ln: int = 0, col: int = 0) -> Any:
        status, value = manager().read(self._h)
        if status != _OK:
            raise self._error(status, ln, col)
        return _unbox(value)

    def write(self, value: Any, *, ln: int = 0, col: int = 0) -> None:
        status = manager().write(self._h, _box(value))
        if status != _OK:
            raise self._error(status, ln, col)

    def move_out(self, *, ln: int = 0, col: int = 0) -> Any:
        status, value = manager().move_out(self._h)
        if status != _OK:
            raise self._error(status, ln, col)
        return _unbox(value)

    def free(self, *, ln: int = 0, col: int = 0) -> None:
        status = manager().free_cell(self._h)
        if status != _OK:
            raise self._error(status, ln, col)

    def _error(self, status: int, ln: int, col: int):
        cls = _STATUS_ERR.get(status, UseAfterFreeError)
        if cls is UseAfterFreeError and self.released:
            from .pointer import freed_message
            return cls(f"{freed_message(self, 'se usa')} (backend nativo)",
                       ln=ln, col=col)
        return cls(f"'{self.name}' {_MSG[cls]} (backend nativo)", ln=ln, col=col)


__all__ = ["NativeCell", "AVAILABLE", "LOAD_ERROR", "manager", "reset", "stats"]
