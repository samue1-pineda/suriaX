"""e2e/enum_suma — variantes con payload: el enum como tipo SUMA.

Un ``enum`` de suriaX tenía una sola lectura: enteros con nombre, estilo C.
Eso alcanza para un conjunto de estados y no alcanza para lo que motiva
tenerlos — describir un árbol, donde cada nodo *es una de estas formas* y cada
forma lleva lo suyo. Sin eso no se escribe un AST, y sin un AST no hay
compilador escrito en el propio lenguaje.

Lo que se fija aquí es la propiedad completa: construir una variante, llevar
su payload, y recuperarlo DESESTRUCTURANDO en un ``match``. La sintaxis del
patrón es la misma que la de la construcción (``Nodo.Literal(v)``), así que lo
que cambia no es la forma sino quién liga: al construir, ``v`` es un valor que
se lee; al hacer match, un nombre que se declara.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import assert_has_code, assert_ok, assert_output  # noqa: E402

W = "fn __write__(str s) -> void;\n"

#: un enum suma con las tres formas: payload simple, múltiple y variante unidad.
NODO = ("enum Nodo {\n"
        "    Literal(int),\n"
        "    Nombre(str),\n"
        "    Suma(int, int),\n"
        "    Fin,\n"
        "};\n")


def _run(body: str, expected: str, extra: str = "") -> None:
    assert_output(W + extra + "\nfn main() -> int {\n" + body + "\n};\n", expected)


# --------------------------------------------------------------------------- #
# construir y desestructurar
# --------------------------------------------------------------------------- #

def test_una_variante_lleva_su_payload():
    _run('    var Nodo n = Nodo.Literal(42);\n'
         '    match (n) { case Nodo.Literal(v) { __write__(f"{v}\\n"); }; };\n'
         '    return 0;', "42\n", extra=NODO)


def test_una_variante_de_varios_valores():
    _run('    var Nodo n = Nodo.Suma(3, 4);\n'
         '    match (n) { case Nodo.Suma(a, b) { __write__(f"{a + b}\\n"); }; };\n'
         '    return 0;', "7\n", extra=NODO)


def test_solo_encaja_la_variante_correcta():
    _run('    var Nodo n = Nodo.Nombre("x");\n'
         '    match (n) {\n'
         '        case Nodo.Literal(v) { __write__("literal\\n"); };\n'
         '        case Nodo.Nombre(s)  { __write__(f"nombre {s}\\n"); };\n'
         '    };\n    return 0;', "nombre x\n", extra=NODO)


def test_una_variante_unidad_convive_con_las_demas():
    _run('    var Nodo n = Nodo.Fin;\n'
         '    match (n) {\n'
         '        case Nodo.Literal(v) { __write__("NO\\n"); };\n'
         '        case Nodo.Fin        { __write__("fin\\n"); };\n'
         '    };\n    return 0;', "fin\n", extra=NODO)


def test_la_variante_tambien_se_nombra_pelada():
    """Los items viven además sin cualificar, igual que en un enum de enteros."""
    _run('    var Nodo n = Literal(9);\n'
         '    match (n) { case Nodo.Literal(v) { __write__(f"{v}\\n"); }; };\n'
         '    return 0;', "9\n", extra=NODO)


def test_el_binding_muere_con_su_rama():
    assert_has_code(
        NODO + "fn f(Nodo n) -> void { match (n) { case Nodo.Literal(v) { }; }; "
               "var int x = v; };", "SEM001")


def test_se_imprime_como_se_escribe():
    _run('    __write__(f"{Nodo.Suma(1, 2)}\\n");\n    return 0;',
         "Suma(1, 2)\n", extra=NODO)


# --------------------------------------------------------------------------- #
# el caso que lo motiva: un árbol y su evaluador
# --------------------------------------------------------------------------- #

ARBOL = ("enum Expr {\n"
         "    Num(int),\n"
         "    Suma(Expr ptr, Expr ptr),\n"
         "    Negado(Expr ptr),\n"
         "};\n"
         "fn evaluar(Expr ptr e) -> int {\n"
         "    match (e) {\n"
         "        case Expr.Num(n)     { return n; };\n"
         "        case Expr.Suma(a, b) { return evaluar(a) + evaluar(b); };\n"
         "        case Expr.Negado(a)  { return 0 - evaluar(a); };\n"
         "    };\n"
         "    return 0;\n};\n")


def test_un_arbol_recursivo_se_evalua():
    """El match desreferencia el sujeto igual que ``.campo``: un árbol se
    escribe con punteros, así que exigir un deref explícito habría hecho
    inescribible justo el caso que motiva los tipos suma."""
    _run('    var Expr dos = Expr.Num(2);\n'
         '    var Expr tres = Expr.Num(3);\n'
         '    var Expr suma = Expr.Suma(&dos, &tres);\n'
         '    var Expr todo = Expr.Negado(&suma);\n'
         '    __write__(f"{evaluar(&todo)}\\n");\n    return 0;',
         "-5\n", extra=ARBOL)


# --------------------------------------------------------------------------- #
# lo que NO se acepta
# --------------------------------------------------------------------------- #

def test_la_aridad_del_constructor_se_verifica():
    assert_has_code(NODO + "fn f() -> void { var Nodo n = Nodo.Literal(1, 2); };",
                    "SEM008")


def test_el_tipo_del_payload_se_verifica():
    assert_has_code(NODO + 'fn f() -> void { var Nodo n = Nodo.Literal("x"); };',
                    "AST006")


def test_la_aridad_del_patron_se_verifica():
    assert_has_code(
        NODO + "fn f(Nodo n) -> void { match (n) { case Nodo.Literal(a, b) { }; }; };",
        "SEM008")


def test_un_patron_liga_nombres_no_expresiones():
    assert_has_code(
        NODO + "fn f(Nodo n) -> void { match (n) { case Nodo.Literal(1 + 2) { }; }; };",
        "SEM001")


def test_una_variante_no_se_contiene_por_valor():
    assert_has_code("enum E { V(E), Fin };", "SEM026")


def test_una_variante_por_puntero_si_es_valida():
    assert_ok("enum E { V(E ptr), Fin };")


def test_void_no_puede_ser_payload():
    assert_has_code("enum E { V(void) };", "SEM025")


def test_un_payload_con_destructor_se_rechaza():
    """Destruir un enum suma exigiría saber QUÉ variante es en ejecución.
    Todavía no existe, así que se rechaza en vez de filtrarse en silencio."""
    assert_has_code(
        "struct { int ptr mutable d; } R;\n"
        "hook fn __free__(R ptr r) -> void { };\n"
        "enum E { V(R), Fin };", "SEM029")


def test_un_puntero_a_algo_con_destructor_si_pasa():
    """Un puntero no posee: no hay nada que destruir al morir la variante."""
    assert_ok("struct { int ptr mutable d; } R;\n"
              "hook fn __free__(R ptr r) -> void { };\n"
              "enum E { V(R ptr), Fin };")


def test_una_variante_con_payload_no_lleva_valor_entero():
    from helpers import parse
    _program, errors, _lex = parse("enum E { V(int) = 3 };")
    assert errors, "se esperaba un error de sintaxis"


# --------------------------------------------------------------------------- #
# el enum de enteros sigue intacto
# --------------------------------------------------------------------------- #

def test_un_enum_sin_payload_sigue_siendo_entero():
    _run('    var int n = Color.VERDE;\n    __write__(f"{n}\\n");\n    return 0;',
         "1\n", extra="enum Color { ROJO, VERDE, AZUL };\n")
