"""e2e/native_memory — el backend de memoria REAL en C++ (``memory_c``).

Valida que punteros, ``&`` y move-semantics corran de verdad por el backend
nativo desacoplado (``runtime/logic_mem/``), y que dé EXACTAMENTE lo mismo que
el fallback en Python puro (differential testing — la razón por la que
``Pointer.mut`` y el estado de celda viajan idénticos en ambos).

Si el ``.so`` no está compilado para el intérprete actual, los tests que
dependen de él se saltan (el frontend nunca depende de esto).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import run_program  # noqa: E402
from runtime.interpreter.memory import native  # noqa: E402

_W = "fn __write__(str s) -> void;\n"


def test_backend_nativo_disponible_y_activo():
    """Por defecto (sin SURIAX_NATIVE_MEM=0) el intérprete usa NativeCell."""
    if not native.AVAILABLE:
        return  # entorno sin el .so: nada que afirmar
    from runtime.interpreter.memory import pointer
    assert pointer.Cell.__name__ == "NativeCell"


def test_memory_class_maquina_de_estados():
    """La lógica LIVE/MOVED/FREED y move-semantics vive en C++."""
    if not native.AVAILABLE:
        return
    from runtime.cxx_api import api
    M = api.load("memory_c").Memory()

    h = M.create(42)
    assert M.read(h) == (0, 42)            # OK
    assert M.write(h, "x") == 0            # revive/escribe
    assert M.read(h) == (0, "x")

    m = M.create(7)
    assert M.move_out(m) == (0, 7)         # transfiere
    assert M.read(m)[0] == 1               # USE_AFTER_MOVE
    assert M.move_out(m)[0] == 3           # DOUBLE_MOVE

    f = M.create(9)
    assert M.free_cell(f) == 0
    assert M.read(f)[0] == 2               # USE_AFTER_FREE
    assert M.free_cell(f) == 4             # DOUBLE_FREE
    assert (M.state(h), M.state(m), M.state(f)) == (0, 1, 2)


#: programa que ejercita '&', deref a través de puntero, campos por puntero,
#: recorrido de lista enlazada y 'move'.
_PROG = _W + """
struct { int v; Nodo ptr? next; } Nodo;
fn suma(Nodo ptr n) -> int {
    var int total = 0;
    var Nodo ptr? cur = n;
    while (cur != null) { total = total + cur.v; cur = cur.next; }
    return total;
}
fn main() -> int {
    var Nodo c = Nodo{ v: 3, next: null };
    var Nodo b = Nodo{ v: 2, next: &c };
    var Nodo a = Nodo{ v: 1, next: &b };
    __write__(f"{suma(&a)}\\n");
    var int x = 10;
    move x;
    return 0;
};
"""


def _prog_output(native_flag: str) -> list:
    """Salida del PROGRAMA (sin el ruido del compilador: rutas de temp, bytes
    del HIR, etc. difieren entre corridas y no son del programa)."""
    prev = os.environ.get("SURIAX_NATIVE_MEM")
    os.environ["SURIAX_NATIVE_MEM"] = native_flag
    try:
        _code, out, _err = run_program(_PROG)
    finally:
        if prev is None:
            os.environ.pop("SURIAX_NATIVE_MEM", None)
        else:
            os.environ["SURIAX_NATIVE_MEM"] = prev
    _noise = ("OK", "volcado", "diagnos", ".phir", "bytes", "===")
    return [ln for ln in out.splitlines()
            if ln and not any(tok in ln for tok in _noise)]


def test_nativo_y_python_dan_lo_mismo():
    """Differential: el backend C++ y el de Python producen idéntica salida DEL
    PROGRAMA (punteros + '&' + lista enlazada + move).

    El estado FREED del backend nativo (RT003) lo cubre además
    ``test_memory.test_usar_despues_de_free_falla_en_runtime``, que corre por
    el nativo cuando está disponible (es el default)."""
    salida_python = _prog_output("0")
    assert "6" in salida_python, salida_python
    if not native.AVAILABLE:
        return
    salida_nativa = _prog_output("1")
    assert salida_nativa == salida_python, (salida_nativa, salida_python)
