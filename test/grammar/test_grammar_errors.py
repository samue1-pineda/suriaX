"""grammar/errors — cada error de sintaxis dispara SU código, y solo ese.

Contrato de la suite negativa aplicado a la gramática: se comprueba el
CÓDIGO (``PAR003``, ``PAR026``...), nunca el texto del mensaje. El objetivo
declarado de estos tests es hacer OBTENIBLE el error: dado un fuente roto de
una forma concreta, saber qué código debe salir y en qué línea, sin leer el
resto del pipeline.

El otro lado del contrato importa igual: la forma VÁLIDA de cada par no debe
producir ningún diagnóstico (cero falsos positivos).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import parse  # noqa: E402


def _codes(source: str):
    """Códigos de los errores léxicos + sintácticos, en orden de aparición."""
    _program, errors, lex_errors = parse(source)
    return [e.code for e in (*lex_errors, *errors)]


def _assert_code(source: str, code: str):
    codes = _codes(source)
    assert code in codes, (
        f"se esperaba {code}; se obtuvo {codes or '(ninguno)'}\n  fuente: {source!r}"
    )


def _assert_clean(source: str):
    codes = _codes(source)
    assert not codes, f"se esperaba sintaxis limpia, hubo {codes}\n  fuente: {source!r}"


def _assert_line(source: str, line: int):
    """El PRIMER error se reporta en la línea indicada (1-based)."""
    _program, errors, lex_errors = parse(source)
    all_errors = [*lex_errors, *errors]
    assert all_errors, f"se esperaba un error\n  fuente: {source!r}"
    first = all_errors[0]
    got = first.loc.line if first.loc is not None else None
    assert got == line, f"error en la línea {got}, se esperaba {line} ({first.code})"


# --------------------------------------------------------------------------- #
# terminadores y delimitadores
# --------------------------------------------------------------------------- #

def test_var_decl_sin_punto_y_coma():
    _assert_code("fn f() -> void { var int a = 1 };", "PAR003")
    _assert_clean("fn f() -> void { var int a = 1; };")


def test_parentesis_sin_cerrar():
    assert _codes("fn f() -> void { var int a = (1 + 2; };"), \
        "un paréntesis sin cerrar debe reportarse"


def test_llave_sin_cerrar():
    assert _codes("fn f() -> void { var int a = 1;"), \
        "una llave sin cerrar debe reportarse"


def test_argumento_sin_coma():
    assert _codes("fn f() -> void { g(1 2); };")


# --------------------------------------------------------------------------- #
# expresiones mal formadas
# --------------------------------------------------------------------------- #

def test_operador_binario_sin_operando_derecho():
    _assert_code("fn f() -> void { var int a = 1 +; };", "PAR012")


def test_expresion_vacia_entre_parentesis():
    assert _codes("fn f() -> void { var int a = (); };")


def test_operador_sin_operando_izquierdo():
    assert _codes("fn f() -> void { var int a = * 2; };")


# --------------------------------------------------------------------------- #
# declaraciones
# --------------------------------------------------------------------------- #

def test_funcion_sin_nombre():
    assert _codes("fn () -> int { return 0; };")


def test_struct_sin_nombre_final():
    """El nombre va DESPUÉS del cuerpo: 'struct { ... } Nombre;'."""
    assert _codes("struct { int x; };")
    _assert_clean("struct { int x; } Punto;")


def test_parametro_sin_tipo():
    """Todo parámetro lleva anotación de tipo (no hay inferencia en la firma)."""
    assert _codes("fn f(a) -> void { };")


def test_enum_sin_llaves():
    assert _codes("enum Color Rojo, Verde;")


# --------------------------------------------------------------------------- #
# formas RETIRADAS del lenguaje: deben seguir siendo error
# --------------------------------------------------------------------------- #

def test_ptr_prefijo_es_error():
    """'ptr' es POSTFIJO ('T ptr'); la forma prefija se retiró."""
    assert _codes("fn f() -> void { ptr int p = null; };")
    _assert_clean("fn f() -> void { var int ptr p = null; };")


def test_mutable_no_califica_variables():
    """'mutable' califica al PUNTERO, no al binding (los bindings usan var/const)."""
    assert _codes("fn f() -> void { mutable int x = 1; };")
    _assert_clean("fn f() -> void { var int ptr mutable p = null; };")


def test_make_ya_no_es_construccion():
    """RBMM fuera del lenguaje v1: 'make T in r' ya no es una expresión...."""
    assert _codes("fn f() -> void { var int ptr y = make int in scratch; };")


def test_make_si_es_un_nombre_valido():
    """...y por eso 'make' vuelve a ser un identificador corriente."""
    _assert_clean("fn make(int n) -> int { return n; };")


# --------------------------------------------------------------------------- #
# directivas y nombres de módulo
# --------------------------------------------------------------------------- #

def test_import_sin_nombre():
    assert _codes("#import ;")


def test_alias_de_modulo_con_palabra_reservada():
    """PAR026: el alias de un '#export' choca con una palabra clave.

    El diagnóstico genérico ('se esperaba IDENTIFIER, se encontro STR') no
    decía nada; este nombra la causa y la salida.
    """
    _assert_code("#import bad.str;", "PAR026")
    _assert_code("#import free;", "PAR026")
    _assert_clean("#import bad.cadena;")


def test_from_sin_import():
    assert _codes("#from IO stdp;")


def test_export_package_sin_as():
    assert _codes("#export package IO")
    _assert_clean("#export package as IO")


# --------------------------------------------------------------------------- #
# literales de struct: la ambigüedad con los bloques
# --------------------------------------------------------------------------- #

def test_campo_de_literal_sin_dos_puntos():
    assert _codes("fn f() -> void { var Nodo n = Nodo{ v 1 }; };")


def test_bloque_suelto_no_es_sentencia():
    """La EBNF no lista 'block' en 'statement'; es lo que hace inequívoco
    reconocer 'Nodo{...}' como literal en posición de expresión."""
    assert _codes("fn f() -> void { { var int x = 1; }; };")


def test_case_con_bloque_no_se_lee_como_literal():
    """Regresión: el patrón de un 'case' no debe comerse el '{' del cuerpo."""
    _assert_clean("fn f() -> void { match (c) { case Origen { g(1); }; } };")


def test_case_sin_llaves_exige_dos_puntos():
    assert _codes("fn f() -> void { match (c) { case Origen g(1); } };")


# --------------------------------------------------------------------------- #
# ubicación: el error apunta a la línea correcta
# --------------------------------------------------------------------------- #

def test_error_reporta_su_linea():
    _assert_line(
        "fn a() -> int { return 0; };\n"
        "fn b() -> int { return 1; };\n"
        "fn c() -> int { return 2 };\n",   # <- falta ';', línea 3
        3,
    )


def test_error_en_la_primera_linea():
    _assert_line("var int a = ;\n", 1)


# --------------------------------------------------------------------------- #
# robustez: nada de esto debe producir un traceback
# --------------------------------------------------------------------------- #

def test_entradas_rotas_no_revientan():
    for source in ("", "{", "}", ";", "fn", "fn f(", "#import", "#",
                   "struct", "case", "}{", "fn f() -> { };", "()"):
        try:
            _codes(source)
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(
                f"{source!r} produjo una excepción no controlada: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
