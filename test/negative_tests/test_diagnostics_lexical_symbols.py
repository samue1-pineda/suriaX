"""negative_tests/diagnostics: lexicos, sintacticos, simbolos y scopes.

Parte de ``test_diagnostics.py`` (partido por tema); lo compartido esta en
``diagnostics_support.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import assert_has_code, error_codes  # noqa: E402

# --------------------------------------------------------------------------- #
# léxicos / sintácticos
# --------------------------------------------------------------------------- #

def test_nombre_que_empieza_por_digito():
    assert_has_code("int 1mal;", "PAR003")


def test_mutable_ya_no_califica_variables():
    codes = error_codes("fn f() -> void { mutable int x = 1; };")
    assert codes, "'mutable int x' debe ser error (usar 'var')"


def test_ptr_prefijo_retirado():
    codes = error_codes("fn f() -> void { ptr int p = null; };")
    assert codes, "'ptr int' (prefijo) ya no es válido: es sufijo postfijo"


def test_break_fuera_de_bucle():
    codes = error_codes("fn f() -> void { break; };")
    assert codes, "'break' fuera de un bucle debe reportarse"


# --------------------------------------------------------------------------- #
# semánticos: símbolos y scopes
# --------------------------------------------------------------------------- #

def test_simbolo_no_declarado():
    assert_has_code("fn f() -> void { var int a = desconocido; };", "SEM001")


def test_simbolo_duplicado_en_el_mismo_scope():
    assert_has_code("fn f() -> void { var int a = 1; var int a = 2; };", "SEM002")


def test_asignar_a_const():
    assert_has_code("fn f() -> void { const int a = 1; a = 2; };", "SEM003")


def test_aridad_de_llamada():
    assert_has_code(
        "fn g(int a, int b) -> int { return a; };\n"
        "fn f() -> void { var int x = g(1); };", "SEM008",
    )


def test_tipo_no_declarado():
    assert_has_code("fn f() -> void { var Inexistente x = null; };", "AST005")


def test_miembro_de_un_nombre_no_declarado():
    """Regresión (H7): 'noexiste.x' era un ICE000 —el SEM001 estaba en una
    rama que no corría nunca y la siguiente línea usaba None—. Ahora es el
    error del nombre, en su posición, y nada más."""
    assert error_codes("fn main() -> int { var int e = noexiste.x; return e; }") \
        == ["SEM001"]
