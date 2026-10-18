"""negative_tests/diagnostics: comparar y ordenar — ``__cmp__``, ``<`` sobre un
parámetro de tipo (SEM039) y los hooks que un enum sin datos no puede tener.

Las reglas que se fijan (ejecutadas en ``e2e/test_comparacion.py``):

 - ``<``/``<=``/``>``/``>=`` sobre un tipo nominal exige su ``__cmp__``; sin
   él es ``AST006`` en el operador, como sobre un ``bool``;
 - dentro de un genérico ``a < b`` con ``a: T`` se ACEPTA y se anota: cada
   instancia comprueba su tipo concreto y la que no se ordena es ``SEM039``
   EN LA LLAMADA, con la línea y la columna de la llamada;
 - ``__cmp__`` tiene firma fija: dos ``T ptr`` del mismo ``T`` y ``int``;
 - un enum sin datos es un entero: ``__eq__``/``__cmp__``/``__hash__`` sobre
   él no se llamarían nunca, y son ``SEM006``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import analyze, assert_has_code, assert_ok, error_codes  # noqa: E402

P = "struct { int x; } P;\n"
CMP_P = "hook fn __cmp__(P ptr a, P ptr b) -> int { return a.x - b.x; }\n"
MENOR = "fn menor<T>(T a, T b) -> bool { return a < b; }\n"


def _con_codigo(source: str, code: str):
    """Los diagnósticos ``code`` de ``source`` (para mirar su posición)."""
    _, _, errores = analyze(source)
    return [e for e in errores if e.code == code]


# --------------------------------------------------------------------------- #
# '__cmp__' sobre un tipo nominal
# --------------------------------------------------------------------------- #

def test_ordenar_un_struct_sin_cmp_es_ast006_en_el_operador():
    fuente = (P + "fn f(P a, P b) -> bool {\n"
              "    return a < b;\n"
              "}\n")
    errores = _con_codigo(fuente, "AST006")
    assert len(errores) == 1, error_codes(fuente)
    # la posición de una operación binaria es la de su comienzo ('a')
    assert (errores[0].line, errores[0].column) == (3, 12), \
        (errores[0].line, errores[0].column)


def test_ordenar_un_struct_con_cmp_compila():
    assert_ok(P + CMP_P + "fn f(P a, P b) -> bool {\n"
              "    return a < b and a <= b and a > b and a >= b;\n}\n")


def test_ordenar_un_enum_suma_con_cmp_compila():
    assert_ok("enum F { A(int), B, };\n"
              "hook fn __cmp__(F ptr a, F ptr b) -> int { return 0; }\n"
              "fn f(F a, F b) -> bool { return a < b; }\n")


def test_ordenar_un_enum_suma_sin_cmp_es_ast006():
    assert_has_code("enum F { A(int), B, };\n"
                    "fn f(F a, F b) -> bool { return a < b; }\n", "AST006")


def test_un_enum_sin_datos_se_ordena_sin_hook():
    assert_ok("enum C { R, V, A, };\n"
              "fn f(C a, C b) -> bool { return a < b; }\n")


def test_bool_sigue_sin_ordenarse():
    """El cambio no abre el orden de lo que no lo tiene."""
    assert_has_code("fn f(bool a, bool b) -> bool { return a < b; }\n", "AST006")


def test_igualdad_de_un_struct_sin_eq_compila():
    """'==' sin '__eq__' es igualdad de valor: no exige nada."""
    assert_ok(P + "fn f(P a, P b) -> bool { return a == b or a != b; }\n")


# --------------------------------------------------------------------------- #
# la firma de '__cmp__'
# --------------------------------------------------------------------------- #

def test_cmp_que_devuelve_bool_es_sem006():
    assert_has_code(P + "hook fn __cmp__(P ptr a, P ptr b) -> bool { return true; }\n",
                    "SEM006")


def test_cmp_con_un_solo_parametro_es_sem006():
    assert_has_code(P + "hook fn __cmp__(P ptr a) -> int { return 0; }\n", "SEM006")


def test_cmp_entre_dos_tipos_distintos_es_sem006():
    """Los dos lados del orden son del mismo tipo: '__cmp__(P, Q)' no lo
    dispararía ninguna comparación (entre tipos distintos ya es AST006)."""
    assert_has_code(P + "struct { int y; } Q;\n"
                    "hook fn __cmp__(P ptr a, Q ptr b) -> int { return 0; }\n",
                    "SEM006")


def test_cmp_con_el_segundo_parametro_por_valor_es_sem006():
    assert_has_code(P + "hook fn __cmp__(P ptr a, P b) -> int { return 0; }\n",
                    "SEM006")


def test_dos_cmp_para_el_mismo_tipo_es_sem007():
    assert_has_code(P + CMP_P + CMP_P, "SEM007")


# --------------------------------------------------------------------------- #
# un enum sin datos es un entero: sus hooks de valor no se llamarían nunca
# --------------------------------------------------------------------------- #

def test_eq_sobre_un_enum_sin_datos_es_sem006():
    fuente = ("enum C { R, V, };\n"
              "hook fn __eq__(C ptr a, C ptr b) -> bool { return true; }\n")
    errores = _con_codigo(fuente, "SEM006")
    assert len(errores) == 1, error_codes(fuente)
    assert errores[0].line == 2, errores[0].line


def test_cmp_y_hash_sobre_un_enum_sin_datos_son_sem006():
    """El hook se mira al final de la pasada: vale aunque el enum se declare
    DESPUÉS que su hook."""
    fuente = ("hook fn __cmp__(C ptr a, C ptr b) -> int { return 0; }\n"
              "hook fn __hash__(C ptr a) -> int { return 0; }\n"
              "enum C { R, V, };\n")
    assert error_codes(fuente).count("SEM006") == 2, error_codes(fuente)


def test_los_hooks_de_valor_de_un_enum_con_datos_son_validos():
    assert_ok("enum F { A(int), B, };\n"
              "hook fn __eq__(F ptr a, F ptr b) -> bool { return true; }\n"
              "hook fn __cmp__(F ptr a, F ptr b) -> int { return 0; }\n"
              "hook fn __hash__(F ptr a) -> int { return 0; }\n")


def test_print_sobre_un_enum_sin_datos_sigue_valiendo():
    """Solo los tres hooks de VALOR: '__print__' sí se despacha (lo decide el
    tipo estático, no el valor)."""
    codes = error_codes("enum C { R, V, };\n"
                        "hook fn __print__(C ptr c) -> void { }\n")
    assert "SEM006" not in codes, codes


# --------------------------------------------------------------------------- #
# '<' sobre un parámetro de tipo: lo decide cada instancia (SEM039)
# --------------------------------------------------------------------------- #

def test_ordenar_un_T_compila():
    """Antes era AST006 en el cuerpo: 'T' no estaba entre los que se ordenan.
    Ahora el cuerpo no está mal; lo juzga cada instancia."""
    assert_ok(MENOR)


def test_instanciar_con_primitivos_ordenables_compila():
    assert_ok(MENOR + "fn main() -> int {\n"
              "    var bool a = menor<int>(1, 2);\n"
              "    var bool b = menor<str>(\"a\", \"b\");\n"
              "    var bool c = menor<float>(1.0, 2.0);\n"
              "    var bool d = menor<char>('a', 'b');\n"
              "    return 0;\n}\n")


def test_instanciar_con_un_tipo_con_cmp_compila():
    assert_ok(P + CMP_P + MENOR + "fn main() -> int {\n"
              "    var bool a = menor<P>(P{ x: 1 }, P{ x: 2 });\n"
              "    return 0;\n}\n")


def test_instanciar_con_un_struct_sin_cmp_es_sem039_en_la_llamada():
    fuente = (P + MENOR + "fn main() -> int {\n"
              "    var bool a = menor<P>(P{ x: 1 }, P{ x: 2 });\n"
              "    return 0;\n}\n")
    errores = _con_codigo(fuente, "SEM039")
    assert len(errores) == 1, error_codes(fuente)
    # la posición es la de la LLAMADA ('menor' en la línea 4), no la del '<'
    assert (errores[0].line, errores[0].column) == (4, 18), \
        (errores[0].line, errores[0].column)


def test_instanciar_con_bool_es_sem039():
    assert_has_code(MENOR + "fn main() -> int {\n"
                    "    var bool a = menor<bool>(true, false);\n"
                    "    return 0;\n}\n", "SEM039")


def test_instanciar_con_un_nullable_es_sem039():
    """null no es menor ni mayor que nada."""
    assert_has_code(MENOR + "fn main() -> int {\n"
                    "    var bool a = menor<int?>(1, 2);\n"
                    "    return 0;\n}\n", "SEM039")


def test_instanciar_con_un_enum_sin_datos_compila():
    assert_ok("enum C { R, V, };\n" + MENOR + "fn main() -> int {\n"
              "    var bool a = menor<C>(C.R, C.V);\n"
              "    return 0;\n}\n")


def test_el_requisito_se_propaga_por_un_generico_intermedio():
    """'envuelve<U>' no ordena nada él mismo, pero llama a 'menor<U>': su
    instancia con 'P' tiene que fallar, y en SU llamada."""
    fuente = (P + MENOR
              + "fn envuelve<U>(U a, U b) -> bool { return menor<U>(a, b); }\n"
              + "fn main() -> int {\n"
              "    var bool a = envuelve<int>(1, 2);\n"
              "    var bool b = envuelve<P>(P{ x: 1 }, P{ x: 2 });\n"
              "    return 0;\n}\n")
    errores = _con_codigo(fuente, "SEM039")
    assert len(errores) == 1, error_codes(fuente)
    assert errores[0].line == 6, errores[0].line


def test_ordenar_un_generico_compuesto_lo_decide_su_cmp():
    """'Caja<T>' no es un parámetro: se ordena si 'Caja' declara '__cmp__',
    sin mirar 'T'."""
    caja = "struct { T v; } Caja<T>;\n"
    assert_has_code(caja + "fn f<T>(Caja<T> a, Caja<T> b) -> bool { return a < b; }\n",
                    "AST006")


def test_sort_de_un_vector_de_un_tipo_sin_cmp_es_sem039():
    fuente = ("#import array.vector as vec\n" + P + "fn main() -> int {\n"
              "    var vec.Vector<P> v = vec.dynamic<P>(1);\n"
              "    v.sort();\n"
              "    return 0;\n}\n")
    errores = _con_codigo(fuente, "SEM039")
    assert len(errores) == 1, error_codes(fuente)
    assert errores[0].line == 5, errores[0].line


def test_sort_de_un_vector_de_un_tipo_con_cmp_compila():
    assert_ok("#import array.vector as vec\n" + P + CMP_P + "fn main() -> int {\n"
              "    var vec.Vector<P> v = vec.dynamic<P>(1);\n"
              "    v.sort();\n"
              "    var vec.Vector<int> w = vec.dynamic<int>(1);\n"
              "    w.sort();\n"
              "    return 0;\n}\n")
