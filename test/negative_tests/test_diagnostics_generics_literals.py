"""negative_tests/diagnostics: SEM038 (genericos que copian T), literales, byte y formatos.

Parte de ``test_diagnostics.py`` (partido por tema); lo compartido esta en
``diagnostics_support.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import assert_has_code, assert_ok  # noqa: E402

# --------------------------------------------------------------------------- #
# SEM038: un generico que COPIA su T, instanciado con un tipo con destructor
# --------------------------------------------------------------------------- #

from helpers import run_source  # noqa: E402

_CON_DESTRUCTOR = ("#import array.vector as vec\n"
                   "#import collections.dictionary as dic\n"
                   "struct { int id; } R;\n"
                   "hook fn __free__(R ptr r) -> void { };\n")


def _diagnosticos(cuerpo: str, extra: str = "") -> str:
    code, out, err = run_source(_CON_DESTRUCTOR + extra +
                                "fn main() -> int {\n" + cuerpo + "\n    return 0;\n};\n")
    return out + err


def test_copiar_un_elemento_con_destructor_es_sem038():
    """``get``, ``v[i]`` y ``v[i] = x`` COPIAN el elemento: con un ``R`` la
    copia y el elemento serian dos dueños. El error sale en la llamada y dice
    DONDE copia el generico."""
    salida = _diagnosticos("    var vec.Vector<R> v = vec.dynamic<R>(1);\n"
                           "    var R a = v.get(0);\n"
                           "    v[0] = R{ id: 1 };")
    assert salida.count("SEM038") == 2, salida
    assert "'get' copia" in salida and "vector.libsrx" in salida, salida
    assert "'__index_set__' copia" in salida, salida


def test_un_generico_sin_destructor_se_sigue_copiando():
    """``Vector<int>.get`` es correcto: la copia de un entero no es un dueño."""
    salida = _diagnosticos("    var vec.Vector<int> v = vec.dynamic<int>(1);\n"
                           "    v.push(1);\n    var int a = v.get(0);\n    v[0] = 2;")
    assert "SEM038" not in salida and "SEM032" not in salida, salida


def test_la_copia_se_propaga_por_otro_generico():
    """``primero<T>`` no copia nada escrito por el, pero llama a ``get``, que
    si: instanciarlo con ``R`` tambien es SEM038."""
    salida = _diagnosticos(
        "    var vec.Vector<R> v = vec.dynamic<R>(1);\n    var R p = primero<R>(&v);",
        extra="fn primero<T>(vec.Vector<T> ptr v) -> T { return v.get(0); };\n")
    assert "SEM038" in salida and "'primero' copia" in salida, salida


def test_los_valores_de_un_diccionario_con_destructor_no_se_copian():
    salida = _diagnosticos("    var dic.Dictionary<str, R> d = dic.make<str, R>(2);\n"
                           "    var R a = d.get(\"x\");")
    assert "SEM038" in salida and "'get' copia" in salida, salida


def test_asignar_un_dueno_por_nombre_es_sem032():
    """Como ligarlo: ``b = a`` dejaria dos dueños. Tambien en un campo de un
    literal."""
    assert_has_code(
        "struct { int id; } R;\n"
        "hook fn __free__(R ptr r) -> void { };\n"
        "fn f() -> int {\n"
        "    var R a = R{ id: 1 };\n"
        "    var R b = R{ id: 2 };\n"
        "    b = a;\n"
        "    return 0;\n"
        "};", "SEM032")
    assert_has_code(
        "struct { int id; } R;\n"
        "hook fn __free__(R ptr r) -> void { };\n"
        "struct { R r; } Caja;\n"
        "fn f() -> int {\n"
        "    var R a = R{ id: 1 };\n"
        "    var Caja c = Caja{ r: a };\n"
        "    return 0;\n"
        "};", "SEM032")


def test_sacar_un_elemento_de_un_bloque_es_sem036():
    """Un elemento es de su BLOQUE, que lo destruye al soltarse: cederlo con
    ``move`` o ``return`` lo destruiria dos veces. Se saca con ``mem.take``."""
    assert_has_code(
        "struct { int id; } R;\n"
        "hook fn __free__(R ptr r) -> void { };\n"
        "fn f(R ptr mutable b) -> R {\n"
        "    return b[0];\n"
        "};", "SEM036")


# --------------------------------------------------------------------------- #
# lote 10: literales, byte y formatos
# --------------------------------------------------------------------------- #

def test_un_literal_con_base_mal_escrito_es_lex007():
    for fuente in ("fn f() -> int { return 0x; };", "fn f() -> int { return 0b102; };",
                   "fn f() -> int { return 1__0; };",
                   "fn f() -> int { return 0x1_0000_0000_0000_0000; };"):
        assert_has_code(fuente, "LEX007")


def test_un_literal_que_no_cabe_en_un_byte():
    assert_has_code("fn f() -> int { var byte b = 256; return 0; };", "AST006")
    assert_has_code("fn f() -> int { var byte b = -1; return 0; };", "AST006")
    assert_ok("fn f() -> int { var byte b = 0xFF; return 0; };")


def test_un_byte_no_hace_aritmetica():
    """Un 'byte' se compara y se enmascara; sumar o desplazar se hace en
    'int', para que un desborde no pase sin verse."""
    assert_has_code("fn f(byte a, byte b) -> int { var byte c = a + b; return 0; };", "AST006")
    assert_has_code("fn f(byte a) -> int { var byte c = a << 1; return 0; };", "AST006")
    assert_has_code("fn f(byte a) -> int { var byte c = -a; return 0; };", "AST006")
    assert_has_code("fn f(byte a, int n) -> int { var bool c = a == n; return 0; };", "AST006")


def test_un_formato_que_no_corresponde_al_tipo():
    for fuente in ('fn f(str s) -> str { return f"{s:x}"; };',
                   'fn f(int n) -> str { return f"{n:.2f}"; };',
                   'fn f(float x) -> str { return f"{x:d}"; };',
                   'fn f(str s) -> str { return f"{s:05}"; };',
                   'fn f(int n) -> str { return f"{n:.2}"; };'):
        assert_has_code(fuente, "AST006")


def test_repr_de_algo_con_un_puntero_se_rechaza():
    """La representacion de lo apuntado podria no terminar (una lista que se
    apunta a si misma)."""
    assert_has_code("struct { int v; N ptr sig; } N;\n"
                    'fn f(N n) -> str { return f"{n!r}"; };', "AST006")


def test_un_formato_con_sintaxis_invalida_es_par012():
    assert_has_code('fn f(int n) -> str { return f"{n:zz}"; };', "PAR012")
