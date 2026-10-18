"""negative_tests: lexico y sintaxis (carril E1 de la tanda de errores locales).

Cada caso fija el CODIGO y la POSICION (linea, columna) del diagnostico, y
que no haya otros detras (las cascadas eran parte de lo que se arreglo). El
texto del mensaje solo se mira cuando el arreglo ES el mensaje (la palabra
reservada, la sugerencia de parentesis o de 'var', el anidamiento).

Los programas que tienen que CORRER estan en
``e2e/test_lexing_parsing_programs.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import analyze, assert_ok, lex, parse  # noqa: E402


def diagnostics(source: str):
    """``[(codigo, linea, columna), ...]`` en orden."""
    _, _, errors = analyze(source)
    return [(e.code, e.line, e.column) for e in errors]


def messages(source: str):
    _, _, errors = analyze(source)
    return [e.message for e in errors]


def main_with(body: str) -> str:
    return "fn main() -> int { " + body + " return 0; }"


# --------------------------------------------------------------------------- #
# 1. f-strings: lo de dentro de '{...}' es codigo
# --------------------------------------------------------------------------- #

def test_a_brace_inside_a_char_literal_does_not_close_the_interpolation():
    assert_ok(main_with("var str s = f\"{'}'}{'{'}\";"))


def test_a_quote_inside_an_interpolation_starts_a_literal():
    assert_ok(main_with('var str s = f"{"a"} {"}"} {f"{1}"}";'))


def test_an_escaped_quote_inside_an_interpolation_is_explained():
    # f"{\"a\"}": el '\' esta en la columna 35; un solo error (antes, ademas,
    # un PAR012 sobre el token ERROR)
    source = main_with('var str s = f"{\\"a\\"}";')
    assert source.index("\\") + 1 == 35
    assert diagnostics(source) == [("LEX005", 1, 35)]


def test_an_escaped_quote_in_a_call_says_how_to_write_it():
    source = main_with('var str s = f"{len(\\"ab\\")}";')
    assert diagnostics(source) == [("LEX005", 1, 39)]
    assert 'f"{len("ab")}"' in messages(source)[0]


def test_the_string_after_the_bad_interpolation_is_not_broken():
    # la cadena se salta entera: lo que sigue en la linea se lee bien (la
    # funcion rota se descarta; la de despues se analiza)
    source = main_with('var str s = f"{\\"a\\"}";') + \
        " fn g() -> int { return desconocido; }"
    assert diagnostics(source) == [("LEX005", 1, 35), ("SEM001", 1, 79)]


def test_a_lexical_error_inside_an_interpolation_says_what_it_is():
    source = main_with('var str s = f"{1_}";')
    assert diagnostics(source) == [("PAR012", 1, 35)]   # donde empieza '1_'
    assert "'_' separa digitos" in messages(source)[0]


# --------------------------------------------------------------------------- #
# 2. literales con exponente: siempre float
# --------------------------------------------------------------------------- #

def _single_token(text: str):
    tokens, errors = lex(text)
    assert not errors, errors
    assert len(tokens) == 2, tokens          # el literal y EOF
    return tokens[0].type.name, tokens[0].value


def test_an_exponent_makes_a_float_literal():
    assert _single_token("1e3") == ("FLOAT_LIT", 1000.0)
    assert _single_token("2.5e-3") == ("FLOAT_LIT", 0.0025)
    assert _single_token("1E+10") == ("FLOAT_LIT", 1e10)
    assert _single_token("1e300") == ("FLOAT_LIT", 1e300)
    assert _single_token("1_0e1_0") == ("FLOAT_LIT", 10e10)


def test_a_based_literal_has_no_exponent():
    assert _single_token("0x1e3") == ("INT_LIT", 0x1E3)


def test_the_literal_and_parse_float_give_the_same_double():
    # el 'float()' que hay detras de text.parse_float en el interprete; la
    # VM usa strtod, que redondea igual (redondeo correcto)
    from runtime.interpreter.intrinsics import _flotante_de
    for text in ("1e3", "2.5e-3", "1E+10", "1e300", "1e-310", "3.25", "0.1e1"):
        assert _single_token(text)[1] == _flotante_de(text), text
    # el literal rechaza lo que se perderia; la funcion, que lee datos, no
    assert _flotante_de("1e-400") == 0.0


def test_a_float_that_overflows_is_an_error():
    assert diagnostics(main_with("var float a = 1e400;")) == [("LEX006", 1, 34)]


def test_a_nonzero_float_that_underflows_to_zero_is_an_error():
    # decision del mantenedor: un literal que no es cero y quedaria en 0.0
    # casi seguro es una errata
    assert diagnostics(main_with("var float a = 1e-400;")) == [("LEX006", 1, 34)]
    # un subnormal si cabe, y un cero escrito como cero no es un error
    assert _single_token("1e-310")[0] == "FLOAT_LIT"
    assert _single_token("0e-400") == ("FLOAT_LIT", 0.0)
    assert _single_token("0.000e5") == ("FLOAT_LIT", 0.0)


def test_an_exponent_without_digits_is_an_error():
    assert diagnostics(main_with("var float a = 1e+;")) == [("LEX007", 1, 34)]


def test_an_exponent_literal_is_not_an_int():
    assert [d[0] for d in diagnostics(main_with("var int a = 1e3;"))] == ["AST006"]


# --------------------------------------------------------------------------- #
# 3. 'dos(a < b, c > (d))': la lectura generica, explicada si falla
# --------------------------------------------------------------------------- #

_DOS = "fn dos(bool x, bool y) -> int { return 1; }\n"
_VARS = "var int b = 2; var int c = 3; var int d = 4; "


def test_the_generic_reading_of_two_comparisons_is_explained():
    source = _DOS + "fn main() -> int { var int a = 1; " + _VARS + \
        "return dos(a < b, c > (d)); }"
    found = diagnostics(source)
    assert [d[0] for d in found] == ["SEM042", "SEM008"]
    first = messages(source)[0]
    assert "GENERICA" in first and "'(a < b)'" in first
    # el aviso va una sola vez
    assert "GENERICA" not in messages(source)[1]


def test_the_explanation_reaches_the_outer_call_when_it_is_the_only_error():
    source = _DOS + "fn a(int z) -> bool { return true; }\n" \
        "fn main() -> int { " + _VARS + "return dos(a < b, c > (d)); }"
    assert [d[0] for d in diagnostics(source)] == ["SEM008"]
    assert "'(a < b)'" in messages(source)[0]


def test_with_parentheses_they_are_comparisons():
    assert_ok(_DOS + "fn main() -> int { var int a = 1; " + _VARS +
              "return dos((a < b), c > (d)); }")


def test_a_real_generic_call_gets_no_explanation():
    program, errors, _ = parse(
        "fn f<T>(T x) -> T { return x; }\n"
        "fn g(int x) -> int { return x; }\n"
        "fn main() -> int { return g(f<int>(3)); }")
    assert not errors
    call = program.items[2].body.statements[0].value
    assert call.ambiguity_hint == "" and call.args[0].ambiguity_hint == ""


# --------------------------------------------------------------------------- #
# 4. posiciones dentro de una f-string
# --------------------------------------------------------------------------- #

def test_each_call_in_an_interpolation_has_its_own_column():
    source = ("fn doble(int x) -> int { return x; }\n"
              'fn main() -> int { var str s = f"{doble(mas_uno(3))}"; return 0; }')
    assert diagnostics(source) == [("SEM001", 2, 41)]
    program, _, _ = parse(source)
    outer = program.items[1].body.statements[0].value.parts[0]
    inner = outer.args[0]
    assert (outer.ln, outer.col) == (2, 35) and (inner.ln, inner.col) == (2, 41)


def test_an_fstring_split_in_two_lines_keeps_each_line():
    source = ("fn main() -> int { var int x = 1;\n"
              '  var str s = f"a{x}"\n'
              '       f"b{  noexiste}"; return 0; }')
    assert diagnostics(source) == [("SEM001", 3, 14)]


def test_a_syntax_error_in_an_interpolation_points_inside_it():
    source = main_with('var str s = f"{ 1 2}";')
    assert diagnostics(source) == [("PAR012", 1, 38)]   # el '2'


# --------------------------------------------------------------------------- #
# 5. cascadas tras la recuperacion
# --------------------------------------------------------------------------- #

def test_no_false_error_on_the_closing_semicolon():
    assert diagnostics("fn main() -> int { var int xs[3]; return 0; };\n"
                       "fn g() -> int { return 0; };") == [("PAR023", 1, 30)]


def test_a_broken_struct_does_not_leave_its_name_behind():
    assert diagnostics("struct { int q } T<A, B>;\n"
                       "fn main() -> int { return 0; }") == [("PAR003", 1, 16)]


def test_a_lexical_error_is_not_repeated_by_the_parser():
    assert diagnostics(main_with("var int x = 1_;")) == [("LEX007", 1, 32)]


def test_an_unknown_escape_does_not_open_another_string():
    assert diagnostics(main_with('var str s = "a\\q"; var char c = \'\\q\';')) \
        == [("LEX005", 1, 32), ("LEX005", 1, 52)]


# --------------------------------------------------------------------------- #
# 6. una palabra reservada como nombre
# --------------------------------------------------------------------------- #

def test_error_as_a_field_name_says_it_is_reserved():
    source = "struct { int error; } S;"
    assert diagnostics(source) == [("PAR003", 1, 14)]   # sin el SEM001 de 'S'
    assert "'error' es una palabra reservada" in messages(source)[0]


def test_any_reserved_word_as_a_name_says_so():
    for source, position in ((main_with("var int if = 3;"), (1, 28)),
                             ("fn while() -> int { return 0; }", (1, 4)),
                             ("fn f(int type) -> int { return 0; }", (1, 10))):
        assert diagnostics(source) == [("PAR003", *position)], source
        assert "palabra reservada" in messages(source)[0], source


# --------------------------------------------------------------------------- #
# 7. PAR025 dice que anida
# --------------------------------------------------------------------------- #

def test_too_deep_blocks_are_called_blocks():
    # 251 'if' anidados: 504 niveles. El parser necesita el margen de pila
    # que le da la CLI (driver), no el de un proceso de pruebas
    n = 251
    source = "fn main() -> int {" + "if (true) {" * n + "return 1;" + "}" * n + \
        "return 0; }"
    previous = sys.getrecursionlimit()
    sys.setrecursionlimit(10_000)
    try:
        found = messages(source)
        assert [d[0] for d in diagnostics(source)] == ["PAR025"]
    finally:
        sys.setrecursionlimit(previous)
    assert "bloques anidados" in found[0] and "operadores" not in found[0]


def test_a_long_operator_chain_is_called_a_chain():
    source = "fn main() -> int { return " + " + ".join(["1"] * 600) + "; }"
    found = messages(source)
    assert [d[0] for d in diagnostics(source)] == ["PAR025"]
    assert "cadena de operadores" in found[0]


# --------------------------------------------------------------------------- #
# 8. un tipo entre parentesis empieza una declaracion
# --------------------------------------------------------------------------- #

def test_an_optional_function_needs_no_var():
    assert_ok("fn f(int x) -> int { return x; }\n"
              "(fn(int) -> int)? g = null;\n"
              "fn main() -> int { (fn(int) -> int)? h = null; "
              "(int ptr)? p = null; return 0; }")


def test_a_parenthesized_expression_statement_is_still_an_expression():
    assert_ok(main_with("var int a = 1; (a) = 2;"))


def test_a_parenthesized_named_type_asks_for_var():
    source = "struct { int v; } Caja;\n" + \
        main_with("(Caja ptr)? p = null;")
    assert diagnostics(source) == [("PAR003", 2, 26)]
    assert "'var (Caja ptr)? p = null;'" in messages(source)[0]
