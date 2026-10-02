"""grammar/exec — la gramática que EJECUTA: parser, HIR e intérprete de acuerdo.

Los otros dos módulos de esta categoría paran en el parser. Éste lleva cada
construcción hasta el final del pipeline y compara la SALIDA, que es lo que
detecta las divergencias entre las tres representaciones: una construcción
puede parsear bien y perderse al emitir el HIR, o llegar al HIR y que el
tree-walk la evalúe de otra forma.

Autocontenidos (prototipo ``__write__``, ligado a un intrínseco del host):
no dependen del estado de ``lib/``. Los que sí ejercitan librerías viven en
``e2e/test_libraries_*.py``.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import assert_output, run_program  # noqa: E402

W = "fn __write__(str s) -> void;\n"


def _run(body: str, expected: str, extra: str = "") -> None:
    """Ejecuta ``body`` como cuerpo de ``main`` y compara stdout."""
    assert_output(W + extra + "\nfn main() -> int {\n" + body + "\n};\n", expected)


# --------------------------------------------------------------------------- #
# expresiones: precedencia y asociatividad REALES (no solo la forma del AST)
# --------------------------------------------------------------------------- #

def test_precedencia_aritmetica():
    _run('__write__(f"{1 + 2 * 3}\\n");', "7\n")


def test_parentesis_cambian_el_resultado():
    _run('__write__(f"{(1 + 2) * 3}\\n");', "9\n")


def test_asociatividad_izquierda():
    _run('__write__(f"{10 - 3 - 2}\\n");', "5\n")   # (10-3)-2, no 10-(3-2)


def test_division_entera():
    _run('__write__(f"{7 / 2}\\n");', "3\n")


def test_comparacion_y_logicos():
    _run('__write__(f"{1 < 2 and 3 > 2}\\n");', "true\n")


def test_or_corta_con_el_primero_verdadero():
    _run('__write__(f"{true or false}\\n");', "true\n")


def test_negacion_y_not():
    _run('__write__(f"{-5} {not true}\\n");', "-5 false\n")


# --------------------------------------------------------------------------- #
# literales e interpolación
# --------------------------------------------------------------------------- #

def test_literales_se_imprimen():
    _run('__write__(f"{10} {1.5} {true} {\'c\'}\\n");', "10 1.5 true c\n")


def test_fstring_con_varias_interpolaciones():
    _run('var int a = 1;\n    var int b = 2;\n'
         '    __write__(f"{a}+{b}={a + b}\\n");', "1+2=3\n")


def test_cadena_plana_no_interpola():
    _run('__write__("literal {a}\\n");', "literal {a}\n")


# --------------------------------------------------------------------------- #
# control de flujo
# --------------------------------------------------------------------------- #

def test_if_else_ejecuta_una_rama():
    _run('if (1 > 2) { __write__("A"); }; else { __write__("B"); };\n'
         '    __write__("\\n");', "B\n")


def test_while_acumula():
    _run('var int i = 0;\n    var int s = 0;\n'
         '    while (i < 5) { s = s + i; i = i + 1; };\n'
         '    __write__(f"{s}\\n");', "10\n")


def test_break_corta_el_bucle():
    _run('var int i = 0;\n'
         '    while (i < 10) { if (i == 3) { break; }; __write__(f"{i} "); i = i + 1; };\n'
         '    __write__("\\n");', "0 1 2 \n")


def test_continue_salta_la_vuelta():
    _run('var int i = 0;\n'
         '    while (i < 5) { i = i + 1; if (i == 3) { continue; }; __write__(f"{i} "); };\n'
         '    __write__("\\n");', "1 2 4 5 \n")


def test_match_despacha_la_rama():
    _run('match (2) { case 1: __write__("uno\\n"); case 2: __write__("dos\\n"); };',
         "dos\n")


def test_match_con_cuerpo_en_bloque():
    """'case X { ... }' — la forma con llaves de la EBNF, sin ':'."""
    _run('match (1) { case 1 { __write__("uno\\n"); }; };', "uno\n")


# --------------------------------------------------------------------------- #
# funciones
# --------------------------------------------------------------------------- #

def test_llamada_y_retorno():
    _run('__write__(f"{doble(21)}\\n");',
         "42\n", extra="fn doble(int n) -> int { return n * 2; };\n")


def test_recursion():
    _run('__write__(f"{fact(5)}\\n");', "120\n",
         extra="fn fact(int n) -> int {\n"
               "    if (n <= 1) { return 1; };\n"
               "    return n * fact(n - 1);\n};\n")


def test_funcion_void_sin_return():
    _run('saluda();', "hola\n",
         extra='fn saluda() -> void { __write__("hola\\n"); };\n')


def test_exit_code_es_el_retorno_de_main():
    code, _out, _err = run_program(W + "fn main() -> int { return 3; };")
    assert code == 3, f"el exit code debe ser el retorno de main, fue {code}"


# --------------------------------------------------------------------------- #
# structs y enums
# --------------------------------------------------------------------------- #

def test_struct_literal_y_campos():
    _run('var P p = P{ x: 3, y: 4 };\n    __write__(f"{p.x + p.y}\\n");',
         "7\n", extra="struct { int x; int y; } P;\n")


def test_struct_literal_anidado():
    _run('var A a = A{ b: B{ v: 5 } };\n    __write__(f"{a.b.v}\\n");', "5\n",
         extra="struct { int v; } B;\nstruct { B b; } A;\n")


def test_asignacion_a_campo():
    _run('var P p = P{ x: 1, y: 1 };\n    p.x = 9;\n    __write__(f"{p.x}\\n");',
         "9\n", extra="struct { int x; int y; } P;\n")


def test_enum_es_entero_estilo_c():
    # el NUMERO se lee con cast<int>: en un f-string un enum sale por su nombre
    _run('__write__(f"{cast<int>(Color.Rojo)} {cast<int>(Color.Verde)} '
         '{cast<int>(Color.Azul)} {Color.Verde}\\n");',
         "0 1 2 Verde\n", extra="enum Color { Rojo, Verde, Azul };\n")


def test_enum_con_valor_explicito_continua_numerando():
    _run('__write__(f"{cast<int>(E.A)} {cast<int>(E.B)} {cast<int>(E.C)} {E.C}\\n");',
         "0 5 6 C\n", extra="enum E { A, B = 5, C };\n")


# --------------------------------------------------------------------------- #
# 'test "..." { }' — los bloques de prueba del propio lenguaje
# --------------------------------------------------------------------------- #

def test_bloques_test_los_ejecuta_el_runner():
    src = W + 'fn main() -> int { return 0; };\n' \
              'test "suma" { __write__("dentro del test\\n"); };\n'
    code, out, _err = run_program(src, args=["--emit-hir"])
    assert code == 0, "el programa con bloques test debe compilar"
