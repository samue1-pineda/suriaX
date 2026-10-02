"""negative_tests/diagnostics: memoria, punteros y consolidacion de structs.

Parte de ``test_diagnostics.py`` (partido por tema); lo compartido esta en
``diagnostics_support.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import assert_has_code, assert_ok  # noqa: E402

# --------------------------------------------------------------------------- #
# semánticos: memoria y punteros
# --------------------------------------------------------------------------- #

def test_use_after_move():
    assert_has_code(
        "fn f() -> void { var int a = 1; move a; var int b = a; };", "SEM004",
    )


def test_double_move():
    assert_has_code(
        "fn f() -> void { var int a = 1; move a; move a; };", "SEM005",
    )


def test_use_after_move_de_un_campo():
    """'move o.it' invalida ese campo (y lo que cuelga de él): usar 'o.it.v'
    después es use-after-move, no un falso negativo diferido al MIR."""
    assert_has_code(
        "struct { int v; } I;\nstruct { I it; } O;\n"
        "fn f() -> void { var O o = O{ it: I{ v: 1 } }; move o.it; "
        "var int x = o.it.v; };", "SEM004",
    )


def test_use_after_move_campo_por_mover_la_variable():
    """Mover la variable completa invalida también sus campos."""
    assert_has_code(
        "struct { int v; } I;\nstruct { I it; } O;\n"
        "fn f() -> void { var O o = O{ it: I{ v: 1 } }; var O c = o; "
        "move o; var int x = o.it.v; };", "SEM004",
    )


# --- propiedad: 'free' termina la propiedad igual que 'move' ---------------- #
# La misma pasada lineal rastrea las dos, porque son las dos formas que tiene
# el lenguaje de terminar una propiedad. Lo que cambia es el MOTIVO, y el
# motivo decide el diagnóstico: recuperarse de un 'move' es posible (el valor
# vive en el nuevo dueño), de un 'free' no.

def test_use_after_free():
    assert_has_code(
        "fn f() -> void { var int x = 1; var int ptr p = &x; free p; "
        "var int ptr q = p; };",
        "SEM023",
    )


def test_double_free():
    assert_has_code(
        "fn f() -> void { var int x = 1; var int ptr p = &x; free p; free p; };",
        "SEM024",
    )


def test_free_de_algo_ya_movido_es_use_after_move():
    """El motivo manda sobre la operación: 'p' se movió, así que ya no es suyo
    para liberarlo — lo liberará su nuevo dueño. No es un doble free."""
    assert_has_code(
        "fn f() -> void { var int x = 1; var int ptr p = &x; move p; free p; };",
        "SEM004",
    )


def test_move_de_algo_ya_liberado_es_use_after_free():
    """Y al revés: mover algo destruido es usarlo, no un doble move."""
    assert_has_code(
        "fn f() -> void { var int x = 1; var int ptr p = &x; free p; move p; };",
        "SEM023",
    )


def test_free_en_una_rama_invalida_despues_del_if():
    """Unión conservadora, igual que 'move': liberado en ALGUNA rama significa
    liberado después. Prefiere el falso positivo cero al falso negativo."""
    assert_has_code(
        "fn f(bool c) -> void { var int x = 1; var int ptr p = &x; "
        "if (c) { free p; }; var int ptr q = p; };",
        "SEM023",
    )


def test_liberar_un_campo_no_toca_al_hermano():
    """'free o.a' invalida ese campo y lo que cuelga de él, nunca al padre ni
    a sus hermanos (mismo criterio que 'move')."""
    assert_ok(
        "struct { int ptr a; int ptr b; } P;\n"
        "fn f() -> void { var int n = 1; var P p = P{ a: &n, b: &n }; "
        "free p.a; var int ptr x = p.b; };"
    )


def test_reasignar_revive_un_valor_liberado():
    """Un valor NUEVO en el mismo nombre no está liberado: el binding revive,
    igual que tras un 'move'."""
    assert_ok(
        "fn f() -> void { var int x = 1; var int ptr p = &x; free p; "
        "p = &x; var int ptr q = p; };"
    )


# --- consolidación del struct: lo que un tipo NO puede ser ------------------ #

def test_un_struct_no_puede_contenerse_por_valor():
    """``struct { S s; } S;`` no cabe en ninguna cantidad de memoria."""
    assert_has_code("struct { S s; int n; } S;", "SEM026")


def test_la_recursion_mutua_por_valor_tambien_es_infinita():
    assert_has_code("struct { B b; } A;\nstruct { A a; } B;", "SEM026")


def test_un_ciclo_de_tres_structs_se_detecta():
    assert_has_code("struct { B b; } A;\nstruct { C c; } B;\n"
                    "struct { A a; } C;", "SEM026")


def test_un_nullable_de_si_mismo_tambien_es_infinito():
    """``S?`` guarda una ``S`` por valor: el envoltorio no cambia el tamaño."""
    assert_has_code("struct { S? sig; int v; } S;", "SEM026")


def test_un_puntero_a_si_mismo_es_valido():
    """La recursión legítima se escribe con un puntero: se REFIERE en vez de
    contener, y ahí sí hay tamaño conocido. Es la misma distinción que decide
    la propiedad."""
    assert_ok("struct { S ptr sig; int v; } S;")


def test_void_no_puede_ser_el_tipo_de_un_campo():
    assert_has_code("struct { void v; } S;", "SEM025")


def test_void_no_puede_ser_el_tipo_de_una_variable():
    assert_has_code("fn f() -> void { var void x; };", "SEM025")


def test_void_no_puede_ser_el_tipo_de_un_parametro():
    """Las tres posiciones de valor se comprueban en un solo punto
    (``TypeBinder.bind``), y por eso ninguna se queda sin cubrir."""
    assert_has_code("fn f(void x) -> void { };", "SEM025")


def test_void_si_es_valido_como_retorno():
    assert_ok("fn f() -> void { };")


def test_un_puntero_a_void_es_valido():
    """``void ptr`` es una dirección sin tipo, no un valor de tipo ``void``."""
    assert_ok("struct { void ptr p; } S;")


def test_un_literal_incompleto_se_rechaza():
    """Sin valores por defecto, un campo que el literal no escribe no existe
    en el valor: leerlo reventaba en runtime, lejos de la causa."""
    assert_has_code("struct { int a; int b; } P;\n"
                    "fn f() -> void { var P p = P{ a: 1 }; };", "SEM028")


def test_un_literal_completo_no_reporta_nada():
    assert_ok("struct { int a; int b; } P;\n"
              "fn f() -> void { var P p = P{ a: 1, b: 2 }; };")


def test_el_valor_de_un_campo_tiene_que_ser_de_su_tipo():
    assert_has_code("struct { int a; } P;\n"
                    "fn f() -> void { var P p = P{ a: \"x\" }; };", "AST006")


def test_null_en_un_campo_no_nullable_se_rechaza():
    assert_has_code("struct { int ptr p; } S;\n"
                    "fn f() -> void { var S s = S{ p: null }; };", "AST006")


def test_null_en_un_campo_nullable_si_pasa():
    assert_ok("struct { int ptr? p; } S;\n"
              "fn f() -> void { var S s = S{ p: null }; };")


def test_escribir_un_campo_con_otro_tipo_se_rechaza():
    """``p.x = "a"`` cruzaba el frontend entero: la rama del ``Identifier``
    comprobaba el tipo del valor y la del campo no."""
    assert_has_code("struct { int x; } P;\n"
                    "fn f(P ptr mutable p) -> void { p.x = \"a\"; };", "AST006")


def test_escribir_un_elemento_con_otro_tipo_se_rechaza():
    """El tipo admitido lo dice ``__index_set__``, no ``__index__``."""
    assert_has_code(
        "struct { int n; } V;\n"
        "hook fn __index_set__(V ptr mutable v, int i, int x) -> void { };\n"
        "fn f(V ptr mutable v) -> void { v[0] = \"a\"; };", "AST006")


def test_escribir_un_elemento_de_su_tipo_si_pasa():
    assert_ok("struct { int n; } V;\n"
              "hook fn __index_set__(V ptr mutable v, int i, int x) -> void { };\n"
              "fn f(V ptr mutable v) -> void { v[0] = 1; };")


def test_un_enum_inicializa_un_int():
    """Los items de un enum son enteros (estilo C). Pasarlo como ARGUMENTO ya
    valía; inicializar y asignar no — la misma pregunta con tres respuestas
    distintas. Ahora las cuatro posiciones comparten predicado."""
    assert_ok("enum Color { ROJO, VERDE };\n"
              "fn f() -> void { var int n = Color.VERDE; n = Color.ROJO; };")


def test_addr_of_sobre_temporal():
    assert_has_code(
        "fn f() -> void { var int a = 1; var int ptr p = &(a + 1); };", "SEM013",
    )


def test_addr_of_sobre_una_funcion():
    """``&f`` sobre una función no es un puntero a función: suriaX no tiene
    tipos función. Antes salía el puntero al tipo de RETORNO —``fn f(int) ->
    int`` daba ``ptr int``—, que es un tipo válido y completamente
    equivocado: se podía pasar donde se esperaba un ``ptr int`` sin que nadie
    dijera nada."""
    assert_has_code(
        "fn g(int x) -> int { return x; };\n"
        "fn f() -> void { var int ptr p = &g; };", "SEM013",
    )


def test_free_sobre_no_puntero():
    assert_has_code("fn f() -> void { var int a = 1; free a; };", "SEM014")


def test_escritura_por_puntero_de_solo_lectura():
    assert_has_code(
        "struct { int x; } P;\n"
        "fn f(P ptr p) -> void { p.x = 1; };", "SEM015",
    )
