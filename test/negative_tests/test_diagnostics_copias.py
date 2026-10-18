"""negative_tests/diagnostics: valor, copia y propiedad.

Tres reglas que salieron juntas de la caza de fallos (``c_errorstfix.md``,
2e) y que se apoyan entre sí:

- ``SEM040``: ``var T x;`` sin valor. Una variable nace con un valor de su
  tipo; antes valía ``null`` aunque el tipo no lo admitiera.
- ``SEM032`` también en ``return g;`` / ``throw g;`` con ``g`` una GLOBAL con
  destructor: devolver por valor COPIA, y la global sigue siendo dueña.
- ``SEM041``: escribir en una COPIA temporal (``v[i].n = 5``, ``v[i].push(x)``,
  ``f().n = 5``). Desde que devolver por valor copia, eso compilaría y no
  haría nada; se pide el elemento prestado con ``at_mut``.

Se comprueban el CÓDIGO y la POSICIÓN (línea, columna), nunca el texto.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import analyze, assert_ok  # noqa: E402


def _diags(source: str) -> list:
    """``[(código, línea, columna)]`` de ``source``, en orden."""
    _, _, errores = analyze(source)
    return [(e.code, e.line, e.column) for e in errores]


def _solo(source: str, esperado: list) -> None:
    obtenido = _diags(source)
    assert obtenido == esperado, f"se esperaba {esperado}; se obtuvo {obtenido}"


# --------------------------------------------------------------------------- #
# SEM040: una variable sin valor
# --------------------------------------------------------------------------- #

def test_una_variable_local_sin_valor_es_sem040():
    _solo("fn f() -> void { var int x; };", [("SEM040", 1, 18)])


def test_una_global_sin_valor_es_sem040():
    _solo("var int g;\nfn f() -> void { };", [("SEM040", 1, 1)])


def test_un_const_sin_valor_tambien():
    _solo("fn f() -> void {\n    const bool b;\n};", [("SEM040", 2, 5)])


def test_un_nullable_sin_valor_tambien_lo_es():
    """``null`` es un valor válido de ``T?``, pero se escribe: el olvido y la
    intención se escriben distinto (``= null``)."""
    _solo("fn f() -> void { var int? x; };", [("SEM040", 1, 18)])


def test_un_struct_sin_valor_es_sem040():
    _solo("struct { int n; } C;\nfn f() -> void { var C c; };",
          [("SEM040", 2, 18)])


def test_con_valor_no_hay_diagnostico():
    assert_ok("var int g = 0;\nfn f() -> void { var int? x = null; "
              "const bool b = false; };")


def test_const_type_sin_valor_sigue_siendo_valido():
    """``const type T;`` declara un TIPO, no una variable."""
    assert_ok("const type int8;\nfn f() -> void { const type L; };")


def test_los_nombres_que_liga_el_lenguaje_no_son_sem040():
    """``catch (e)``, ``case A(x)`` y ``with`` nacen siempre con un valor."""
    assert_ok("enum E { A(int), B };\n"
              "fn f(E e) -> int {\n"
              "    try { throw 1; } catch (int x) { };\n"
              "    match (e) { case A(n): { return n; } case B: { return 0; } };\n"
              "    return 0;\n"
              "};")


def test_la_reserva_de_un_contenedor_no_es_una_variable_sin_valor():
    """``int vec.Vector v[4];`` no lleva '=' pero sí valor: la reserva."""
    assert_ok("#import array.vector as vec\n"
              "fn f() -> void { int vec.Vector v[4]; v.push(1); };")


# --------------------------------------------------------------------------- #
# SEM032: devolver (o lanzar) una global con destructor
# --------------------------------------------------------------------------- #

_R = ("struct { int id; } R;\n"
      "hook fn __free__(R ptr r) -> void { };\n"
      "struct { R r; int k; } Par;\n"
      "var R g = R{ id: 1 };\n"
      "var Par gp = Par{ r: R{ id: 2 }, k: 0 };\n")   # 5 líneas


def test_devolver_una_global_con_destructor_es_sem032():
    _solo(_R + "fn f() -> R { return g; };", [("SEM032", 6, 22)])


def test_devolver_el_campo_de_una_global_con_destructor_es_sem032():
    _solo(_R + "fn f() -> R { return gp.r; };", [("SEM032", 6, 22)])


def test_lanzar_una_global_con_destructor_es_sem032():
    _solo(_R + "fn f() -> void { throw g; };", [("SEM032", 6, 24)])


def test_entregar_la_global_con_move_es_valido():
    assert_ok(_R + "fn f() -> R { return move g; };\n"
                   "fn h() -> void { throw move gp.r; };")


def test_devolver_un_local_con_destructor_lo_mueve_y_es_valido():
    assert_ok(_R + "fn f() -> R { var R r = R{ id: 3 }; return r; };\n"
                   "fn h() -> R { var Par p = Par{ r: R{ id: 4 }, k: 1 }; "
                   "return p.r; };")


def test_prestar_la_global_es_valido():
    assert_ok(_R + "fn f() -> R ptr { return &g; };")


def test_devolver_una_global_sin_destructor_es_valido():
    """Sin destructor la copia no duplica ningún recurso."""
    assert_ok("struct { int n; } C;\nvar C c = C{ n: 1 };\n"
              "fn f() -> C { return c; };\nfn h() -> int { return c.n; };")


# --------------------------------------------------------------------------- #
# SEM041: escribir en una copia temporal
# --------------------------------------------------------------------------- #

_V = ("#import array.vector as vec\n"
      "struct { int n; } C;\n"
      "@impl C { fn sube(C ptr mutable self) -> void { self.n = self.n + 1; } };\n"
      "struct { C c; } Env;\n"
      "fn dame() -> C { return C{ n: 1 }; };\n"
      "fn lista() -> vec.Vector<int> { return vec.dynamic<int>(1); };\n")  # 6


def _cuerpo(sentencias: str) -> str:
    return (_V + "fn f() -> void {\n"
            "    var vec.Vector<C> v = vec.dynamic<C>(2);\n"
            "    var vec.Vector<vec.Vector<int>> vv = vec.dynamic<vec.Vector<int>>(2);\n"
            "    var vec.Vector<Env> ve = vec.dynamic<Env>(2);\n"
            f"    {sentencias}\n"
            "};")   # la sentencia queda en la línea 11


def test_asignar_al_campo_de_v_i_es_sem041():
    _solo(_cuerpo("v[0].n = 5;"), [("SEM041", 11, 5)])


def test_asignar_a_un_campo_anidado_de_v_i_es_sem041():
    _solo(_cuerpo("ve[0].c.n = 5;"), [("SEM041", 11, 5)])


def test_un_metodo_que_modifica_sobre_v_i_es_sem041():
    _solo(_cuerpo("vv[0].push(5);"), [("SEM041", 11, 5)])


def test_un_metodo_propio_que_modifica_sobre_v_i_es_sem041():
    _solo(_cuerpo("v[0].sube();"), [("SEM041", 11, 5)])


def test_asignar_al_campo_del_resultado_de_una_llamada_es_sem041():
    _solo(_cuerpo("dame().n = 5;"), [("SEM041", 11, 5)])


def test_asignar_al_campo_de_get_es_sem041():
    _solo(_cuerpo("v.get(0).n = 5;"), [("SEM041", 11, 5)])


def test_indexar_para_escribir_el_resultado_de_una_llamada_es_sem041():
    """``lista()[0] = 1``: el '__index_set__' escribiría en una copia."""
    _solo(_cuerpo("lista()[0] = 1;"), [("SEM041", 11, 5)])


def test_el_prestamo_mutable_si_modifica_y_es_valido():
    assert_ok(_cuerpo("v.at_mut(0).n = 5; v.at_mut(0).sube(); "
                      "vv.at_mut(0).push(5); vv.at_mut(0)[0] = 1; "
                      "ve.at_mut(0).c.n = 2;"))


def test_reemplazar_el_elemento_entero_es_valido():
    assert_ok(_cuerpo("v[0] = C{ n: 2 }; vv[0] = vec.dynamic<int>(1);"))


def test_leer_de_una_copia_es_valido():
    assert_ok(_cuerpo("var int a = v[0].n; var int b = vv[0].len(); "
                      "var int c = dame().n;"))


def test_un_metodo_que_modifica_sobre_el_resultado_de_una_llamada_es_valido():
    """El resultado de una llamada es NUEVO, no la copia de algo guardado, y
    el método puede hacer algo más (``abrir(...).write(...)``)."""
    assert_ok(_cuerpo("dame().sube(); lista().push(3);"))


def test_escribir_a_traves_de_un_puntero_o_un_bloque_crudo_es_valido():
    assert_ok("#import mem\n"
              "struct { int n; } C;\n"
              "fn f(C ptr mutable p) -> void {\n"
              "    p.n = 1;\n"
              "    var C ptr mutable b = mem.reserve<C>(2);\n"
              "    b[0] = C{ n: 1 };\n"
              "    b[0].n = 2;\n"
              "    mem.release<C>(b);\n"
              "};")
