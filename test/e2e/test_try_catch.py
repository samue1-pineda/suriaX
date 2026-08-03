"""e2e/try_catch — propagación de errores por excepciones, a fondo.

``throw`` inicia la propagación de un valor por la pila de llamadas; el
``try`` más cercano la intercepta, liga el valor al nombre del ``catch`` y
ejecuta su bloque. Un ``throw`` que escapa de todo ``catch`` aborta con
código 70.

Lo que se ejercita aquí no es la sintaxis (eso es ``grammar/``) sino la
INTERACCIÓN con el resto del control de flujo: bucles, ``break``/
``continue``, ``return`` dentro del ``try`` y del ``catch``, anidamiento y
re-lanzado, y el desenrollado a través de muchos marcos de pila.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import assert_output, run_program  # noqa: E402

W = "fn __write__(str s) -> void;\n"


def _run(body: str, expected: str, extra: str = "") -> None:
    assert_output(W + extra + "\nfn main() -> int {\n" + body + "\n};\n", expected)


# --------------------------------------------------------------------------- #
# captura básica y propagación
# --------------------------------------------------------------------------- #

def test_captura_en_el_mismo_bloque():
    _run("""
    try {
        throw 7;
        __write__("inalcanzable\\n");
    } catch (e) {
        __write__(f"cap {e}\\n");
    };
    return 0;""", "cap 7\n")


def test_el_catch_se_salta_si_no_hay_throw():
    _run("""
    try { __write__("ok\\n"); } catch (e) { __write__("NO\\n"); };
    return 0;""", "ok\n")


def test_propagacion_desde_una_funcion():
    _run("""
    try { boom(); } catch (e) { __write__(f"cap {e}\\n"); };
    return 0;""", "cap 42\n",
         extra="fn boom() -> error int { throw 42; };\n")


def test_propagacion_por_dos_niveles():
    _run("""
    try { outer(); } catch (e) { __write__(f"cap {e}\\n"); };
    return 0;""", "cap 9\n",
         extra="fn inner() -> error int { throw 9; };\n"
               "fn outer() -> error int { return inner(); };\n")


def test_propagacion_a_traves_de_recursion_profunda():
    """El desenrollado atraviesa 50 marcos sin perder el valor."""
    _run("""
    try { deep(50); } catch (e) { __write__(f"cap {e}\\n"); };
    return 0;""", "cap 0\n",
         extra="fn deep(int n) -> error int {\n"
               "    if (n == 0) { throw 0; };\n"
               "    return deep(n - 1);\n};\n")


def test_se_puede_lanzar_una_cadena():
    _run("""
    try { throw "roto"; } catch (e) { __write__(f"cap {e}\\n"); };
    return 0;""", "cap roto\n")


# --------------------------------------------------------------------------- #
# anidamiento y re-lanzado
# --------------------------------------------------------------------------- #

def test_el_try_interno_captura_y_el_externo_no_se_entera():
    _run("""
    try {
        try { throw 1; } catch (e) { __write__(f"in {e}\\n"); };
        __write__("sigue\\n");
    } catch (e) {
        __write__("el externo NO debe capturar\\n");
    };
    return 0;""", "in 1\nsigue\n")


def test_relanzar_desde_el_catch_lo_captura_el_externo():
    _run("""
    try {
        try { throw 1; } catch (e) { __write__("in\\n"); throw 2; };
    } catch (e) {
        __write__(f"out {e}\\n");
    };
    return 0;""", "in\nout 2\n")


# --------------------------------------------------------------------------- #
# interacción con bucles y con 'return'
# --------------------------------------------------------------------------- #

def test_un_throw_desde_dentro_del_bucle_lo_corta():
    _run("""
    try {
        var int i = 0;
        while (i < 10) {
            if (i == 3) { throw i; };
            __write__(f"{i} ");
            i = i + 1;
        };
    } catch (e) { __write__(f"| cap {e}\\n"); };
    return 0;""", "0 1 2 | cap 3\n")


def test_try_dentro_del_bucle_captura_cada_vuelta():
    _run("""
    var int i = 0;
    while (i < 3) {
        try { throw i; } catch (e) { __write__(f"c{e} "); };
        i = i + 1;
    };
    __write__("\\n");
    return 0;""", "c0 c1 c2 \n")


def test_break_dentro_de_un_try_sale_del_bucle():
    _run("""
    var int i = 0;
    while (i < 5) {
        try {
            if (i == 2) { break; };
            __write__(f"{i} ");
        } catch (e) { __write__("NO"); };
        i = i + 1;
    };
    __write__("\\n");
    return 0;""", "0 1 \n")


def test_continue_dentro_de_un_try_salta_la_vuelta():
    _run("""
    var int i = 0;
    while (i < 4) {
        i = i + 1;
        try {
            if (i == 2) { continue; };
            __write__(f"{i} ");
        } catch (e) { __write__("NO"); };
    };
    __write__("\\n");
    return 0;""", "1 3 4 \n")


def test_return_dentro_del_try():
    code, out, _err = run_program(
        W + 'fn main() -> int { try { __write__("t\\n"); return 5; } '
            "catch (e) { return 1; }; return 0; };")
    assert "t\n" in out and code == 5, f"exit={code} out={out!r}"


def test_return_dentro_del_catch():
    code, out, _err = run_program(
        W + 'fn main() -> int { try { throw 3; } '
            'catch (e) { __write__("c\\n"); return 4; }; return 0; };')
    assert "c\n" in out and code == 4, f"exit={code} out={out!r}"


# --------------------------------------------------------------------------- #
# scope del binding y throw no capturado
# --------------------------------------------------------------------------- #

def test_el_binding_del_catch_vive_solo_en_su_bloque():
    _run("""
    try { throw 1; } catch (e) { __write__(f"{e}\\n"); };
    __write__("fin\\n");
    return 0;""", "1\nfin\n")


def test_usar_el_binding_fuera_del_catch_es_error():
    code, _out, err = run_program(
        W + "fn main() -> int { try { throw 1; } catch (e) { }; "
            '__write__(f"{e}"); return 0; };')
    assert code != 0 and "SEM001" in err, err


def test_throw_no_capturado_aborta_con_codigo_70():
    code, _out, err = run_program(W + "fn main() -> int { throw 99; return 0; };")
    assert code == 70, f"exit={code}"
    assert "99" in err, err


def test_throw_no_capturado_desde_una_funcion_anidada():
    code, _out, _err = run_program(
        W + "fn boom() -> error int { throw 1; };\n"
            "fn main() -> int { boom(); return 0; };")
    assert code == 70, f"exit={code}"
