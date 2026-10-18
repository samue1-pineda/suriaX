"""negative_tests/diagnostics: cero falsos positivos (programas validos).

Parte de ``test_diagnostics.py`` (partido por tema); lo compartido esta en
``diagnostics_support.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import assert_ok, error_codes  # noqa: E402

# --------------------------------------------------------------------------- #
# CERO FALSOS POSITIVOS: programas válidos que NO deben dar diagnósticos
# --------------------------------------------------------------------------- #

def test_valido_shadowing_en_scope_anidado():
    """Redeclarar en un scope INTERNO no colisiona con el externo.

    El scope interno se abre con una construcción de control (``if``): un
    bloque SUELTO ``{ }`` no es una sentencia de la gramática (ver
    ``grammar.ebnf``, regla ``statement``) aunque el HIR sí sepa transportarlo."""
    assert_ok("fn f() -> void { var int a = 1; if (true) { var int a = 2; }; };")


def test_valido_reasignar_revive_un_movido():
    assert_ok("fn f() -> void { var int a = 1; move a; a = 2; var int b = a; };")


def test_valido_puntero_mutable_escribe():
    assert_ok("struct { int x; } P;\nfn f(P ptr mutable p) -> void { p.x = 1; };")


def test_valido_cast_entre_primitivos():
    assert_ok("fn f() -> void { var float x = cast<float>(3); "
              "var int y = cast<int>(x); };")


def test_valido_try_catch_y_throw():
    assert_ok(
        "fn g() -> error int { throw 1; };\n"
        "fn f() -> void { try { var int x = g(); } catch (e) { }; };"
    )


def test_valido_bloque_test():
    assert_ok('test "caso" { var int a = 1; expect (a == 1); };')


def test_valido_enum_es_asignable_a_int():
    """Los items de un enum son enteros (estilo C): pasar uno a un 'int' es
    válido (ver e2e/grammar 'test_enum_y_match')."""
    assert_ok(
        "enum E { A, B, C };\nfn g(int n) -> void { };\n"
        "fn f() -> void { g(A); };"
    )


def test_valido_argumento_puntero_mutable_a_solo_lectura():
    """'ptr mutable T' donde se espera 'ptr T': soltar el permiso de escritura
    siempre es seguro — no debe reportarse."""
    assert_ok(
        "struct { int v; } B;\nfn g(B ptr b) -> int { return b.v; };\n"
        "fn f() -> void { var B x = B{ v: 1 }; var int n = g(&x); };"
    )


def test_valido_mover_un_campo_no_afecta_al_hermano():
    assert_ok(
        "struct { int v; } I;\nstruct { I a; I b; } P;\n"
        "fn f() -> void { var P p = P{ a: I{v:1}, b: I{v:2} }; "
        "move p.a; var int x = p.b.v; };"
    )


def test_valido_reasignar_un_campo_movido_lo_revive():
    assert_ok(
        "struct { int v; } I;\nstruct { I it; } O;\n"
        "fn f() -> void { var O o = O{ it: I{v:1} }; move o.it; "
        "o.it = I{v:9}; var int x = o.it.v; };"
    )


def test_valido_struct_recursivo_con_punteros():
    assert_ok(
        "struct { int v; Node ptr? next; } Node;\n"
        "fn f() -> void { var Node n = Node{ v: 1, next: null }; };"
    )


def test_valido_catch_liga_solo_en_su_bloque():
    """El binding del catch NO se filtra fuera de su bloque."""
    codes = error_codes(
        "fn f() -> void { try { } catch (e) { }; var int x = e; };"
    )
    assert "SEM001" in codes, (
        f"'e' no debería existir fuera del catch; códigos: {codes}"
    )
