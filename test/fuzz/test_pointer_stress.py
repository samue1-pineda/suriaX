"""fuzz/pointer_stress — pruebas EXTREMAS de punteros y del backend de memoria.

Martilla el core C++ (``memory_c``) a escala y con casos adversariales
(use-after-move/free, doble move/free, handle inválido), y ejercita cadenas de
punteros profundas de punta a punta, comparando el backend nativo con el de
Python (differential a escala). Si el ``.so`` no está compilado, los tests que
dependen del nativo se saltan.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import omitir, run_program  # noqa: E402
from runtime.interpreter.memory import native  # noqa: E402


def _exigir_nativo() -> None:
    """Omite la prueba (visible, con la causa) si ``memory_c`` no cargó.

    Antes era ``if not native.AVAILABLE: return``: la prueba "pasaba" sin
    ejecutar nada, en esta máquina y en la CI, que no construye el módulo.
    """
    if not native.AVAILABLE:
        omitir(f"el módulo nativo 'memory_c' no cargó ({native.LOAD_ERROR}); "
               "constrúyelo con: cmake -S . -B build && "
               "cmake --build build --target suriax-native")


_W = "fn __write__(str s) -> void;\n"


def _M():
    from runtime.cxx_api import api
    return api.load("memory_c").Memory()


# --------------------------------------------------------------------------- #
# escala: masa de celdas por el backend nativo
# --------------------------------------------------------------------------- #

def test_masa_de_cien_mil_celdas():
    _exigir_nativo()
    M = _M()
    N = 100_000
    hs = [M.create(i) for i in range(N)]
    assert M.total() == N and M.live_count() == N
    # lecturas dispersas correctas
    for i in range(0, N, 997):
        assert M.read(hs[i]) == (0, i)
    # mueve las pares, libera las impares
    for i in range(0, N, 2):
        assert M.move_out(hs[i]) == (0, i)
    for i in range(1, N, 2):
        assert M.free_cell(hs[i]) == 0
    assert M.live_count() == 0
    assert M.read(hs[0])[0] == 1   # movida -> USE_AFTER_MOVE
    assert M.read(hs[1])[0] == 2   # liberada -> USE_AFTER_FREE
    M.reset()
    assert M.total() == 0


# --------------------------------------------------------------------------- #
# adversarial: cada violación devuelve su código exacto, sin crashear
# --------------------------------------------------------------------------- #

def test_adversarial_estados_de_celda():
    _exigir_nativo()
    M = _M()
    h = M.create(1)
    assert M.move_out(h) == (0, 1)
    assert M.move_out(h)[0] == 3     # DOUBLE_MOVE
    assert M.read(h)[0] == 1         # USE_AFTER_MOVE
    assert M.write(h, 7) == 0        # write REVIVE una celda movida
    assert M.read(h) == (0, 7)

    f = M.create(2)
    assert M.free_cell(f) == 0
    assert M.free_cell(f) == 4       # DOUBLE_FREE
    assert M.read(f)[0] == 2         # USE_AFTER_FREE
    assert M.write(f, 9) == 2        # escribir tras free -> USE_AFTER_FREE


def test_handle_invalido_no_crashea():
    """Un handle que no existe devuelve BAD_HANDLE (5), no un segfault."""
    _exigir_nativo()
    M = _M()
    bad = 2 ** 40
    assert M.read(bad)[0] == 5        # BAD_HANDLE
    assert M.move_out(bad)[0] == 5
    assert M.write(bad, 1) == 5
    assert M.free_cell(bad) == 5
    assert M.state(bad) == -1


def test_ciclo_intenso_move_write_revive():
    """Miles de ciclos move→write→read sobre la misma celda (revivir)."""
    _exigir_nativo()
    M = _M()
    h = M.create(0)
    for i in range(50_000):
        assert M.move_out(h)[0] == 0
        assert M.write(h, i) == 0
        assert M.read(h) == (0, i)


# --------------------------------------------------------------------------- #
# end-to-end: cadena de punteros profunda, differential nativo vs python
# --------------------------------------------------------------------------- #

def _chain_program(n: int) -> str:
    """Programa con ``n`` nodos encadenados por ``&`` y recorridos por puntero."""
    decls = "\n    ".join(
        f"var Nodo x{i} = Nodo{{ v: {i}, next: {'&x' + str(i - 1) if i else 'null'} }};"
        for i in range(n)
    )
    return (
        _W
        + "struct { int v; Nodo ptr? next; } Nodo;\n"
        + "fn suma(Nodo ptr h) -> int { var int t = 0; var Nodo ptr? c = h; "
          "while (c != null) { t = t + c.v; c = c.next; }; return t; };\n"
        + "fn main() -> int {\n    " + decls
        + f"\n    __write__(f\"{{suma(&x{n - 1})}}\\n\");\n    return 0;\n}};\n"
    )


def _prog_lines(src: str, native_flag: str) -> list:
    prev = os.environ.get("SURIAX_NATIVE_MEM")
    os.environ["SURIAX_NATIVE_MEM"] = native_flag
    try:
        _code, out, _err = run_program(src)
    finally:
        if prev is None:
            os.environ.pop("SURIAX_NATIVE_MEM", None)
        else:
            os.environ["SURIAX_NATIVE_MEM"] = prev
    noise = ("OK", "volcado", "diagnos", ".phir", "bytes", "===")
    return [ln for ln in out.splitlines()
            if ln and not any(tok in ln for tok in noise)]


def test_cadena_de_punteros_profunda_differential():
    """200 nodos encadenados por '&', recorridos por puntero: suma 0..199 =
    19900, idéntico en el backend nativo y en el de Python."""
    src = _chain_program(200)
    py = _prog_lines(src, "0")
    assert "19900" in py, py
    _exigir_nativo()
    nat = _prog_lines(src, "1")
    assert nat == py, (nat, py)


def test_el_error_de_memoria_es_panic():
    """Contrato de severidad: los errores de memoria son 'panic'."""
    from runtime.interpreter.errors import (
        DoubleMoveError, UseAfterFreeError, UseAfterMoveError,
    )
    assert UseAfterMoveError.severity == "panic"
    assert UseAfterFreeError.severity == "panic"
    assert DoubleMoveError.severity == "panic"
