"""negative_tests/diagnostics: tipos, conversiones y structs.

Parte de ``test_diagnostics.py`` (partido por tema); lo compartido esta en
``diagnostics_support.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import assert_has_code, assert_ok  # noqa: E402

# --------------------------------------------------------------------------- #
# semánticos: tipos y conversiones
# --------------------------------------------------------------------------- #

def test_inicializador_de_tipo_incompatible():
    assert_has_code('fn f() -> void { var int a = "texto"; };', "AST006")


def test_null_a_tipo_no_nullable():
    assert_has_code("fn f() -> void { var int a = null; };", "AST006")


def test_retorno_de_tipo_incorrecto():
    assert_has_code('fn f() -> int { return "texto"; };', "AST012")


def test_operacion_entre_tipos_incompatibles():
    assert_has_code('fn f() -> void { var int a = 1 + "x"; };', "AST006")


def test_argumento_de_tipo_incompatible():
    """El TIPO de cada argumento se verifica contra su parámetro (sin
    coerciones implícitas: 'g(int)' donde 'g' espera 'str' es AST006). Para
    imprimir un entero se usa una f-string ('print(f\"{x}\")')."""
    assert_has_code(
        "fn g(str s) -> void { };\n"
        "fn f() -> void { var int c = 5; g(c); };", "AST006",
    )


def test_argumento_puntero_mutable_desde_const():
    """Pasar 'ptr T' donde se espera 'ptr mutable T' permitiría mutar un
    'const' a través de la función: se rechaza (const-correctness)."""
    assert_has_code(
        "struct { int v; } B;\n"
        "fn g(B ptr mutable b) -> void { b.v = 1; };\n"
        "fn f() -> void { const B c = B{ v: 0 }; g(&c); };", "AST006",
    )


def test_argumento_nominal_incorrecto():
    """Pasar '&O' donde se espera 'B ptr' (nominales distintos) es error de
    tipos en compilación, no una confusión de tipos que explota en runtime."""
    assert_has_code(
        "struct { int v; } B;\nstruct { int w; } O;\n"
        "fn g(B ptr b) -> int { return b.v; };\n"
        "fn f() -> void { var O o = O{ w: 1 }; var int x = g(&o); };", "AST006",
    )


def test_cast_sin_conversion_nativa():
    """``int -> bool`` no es un par nativo: la vuelta (``bool -> int``) sí,
    pero decidir qué entero es 'verdadero' es una convención, no una
    conversión."""
    assert_has_code("fn f() -> void { var bool b = cast<bool>(5); };", "SEM016")


def test_cast_a_str_si_es_nativo():
    """Todo primitivo tiene forma de texto —la que ya interpolaba un
    f-string—, así que ``cast<str>`` no puede fallar y no necesita hook."""
    assert_ok("fn f() -> void {\n"
              "    var str a = cast<str>(5);\n"
              "    var str b = cast<str>(1.5);\n"
              "    var str c = cast<str>(true);\n"
              "    var str d = cast<str>('z');\n};")


def test_cast_a_nominal_sin_hook():
    assert_has_code(
        "const type int8;\nfn f() -> void { var int8 b = cast<int8>(1); };",
        "SEM016",
    )


# El inicializador de un 'type_decl' NO lo visitaba ninguna pasada: 'ast.TypeDecl'
# faltaba en el despacho del scope_resolver y 'visit_stmt' ignora en silencio lo
# que no tiene handler. Un nombre inexistente cruzaba el frontend entero y solo
# lo veia el runtime (RT006, "brecha del analisis estatico").

def test_inicializador_de_type_decl_resuelve_sus_nombres():
    assert_has_code("const type Bloque = _no_existe(4);", "SEM001")


def test_inicializador_de_type_decl_tambien_dentro_de_una_funcion():
    """El inicializador de un 'type' ANIDADO tambien pasa por la Semantica."""
    assert_has_code("fn f() -> void { const type L = _no_existe(1); };", "SEM001")


def test_inicializador_de_type_decl_debe_producir_un_tipo():
    """'type' es un metatipo: inicializarlo con un valor normal es AST006."""
    assert_has_code("const type Malo = 5;", "AST006")


def test_type_decl_con_inicializador_valido_compila_limpio():
    """El otro lado del contrato: una 'fn ... -> type' SI es un inicializador
    valido, y el arreglo no puede convertirlo en un falso positivo."""
    assert_ok("fn entero_de(int bits) -> type;\nconst type int8 = entero_de(8);")


def test_type_decl_sin_inicializador_sigue_limpio():
    assert_ok("const type int8;")


def test_un_type_en_el_nivel_superior_sigue_siendo_valido():
    assert_ok("const type int8;\nfn f() -> void { const int8? x = null; };")


# --------------------------------------------------------------------------- #
# semánticos: structs
# --------------------------------------------------------------------------- #

def test_campo_inexistente_en_literal():
    assert_has_code(
        "struct { int x; } P;\nfn f() -> void { var P p = P{ y: 1 }; };", "SEM001",
    )


def test_campo_repetido_en_literal():
    assert_has_code(
        "struct { int x; } P;\nfn f() -> void { var P p = P{ x: 1, x: 2 }; };",
        "SEM002",
    )


def test_literal_de_tipo_que_no_es_struct():
    assert_has_code(
        "enum E { A };\nfn f() -> void { var E e = E{ A: 1 }; };", "AST005",
    )


def test_campo_inexistente_en_acceso():
    assert_has_code(
        "struct { int x; } P;\n"
        "fn f(P ptr p) -> int { return p.zzz; };", "SEM001",
    )
