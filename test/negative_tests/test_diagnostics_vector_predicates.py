"""negative_tests/diagnostics: 'any', 'all', 'count_if' y 'find' de 'Vector'.

- El predicado es un ``fn(T ptr) -> bool``: otro tipo de función (o una
  lambda con otros tipos) es ``AST006`` en el argumento, y otra aridad,
  ``SEM008``.
- 'find' devuelve un ``int?``: no entra en un ``int`` ni se suma sin
  desenvolver (``AST006``).
- Las cuatro le pasan al predicado una COPIA del elemento, así que con un
  ``T`` que tiene destructor son ``SEM038`` en la llamada.

Va por ``analyze`` y no por ``helpers.error_codes``/``assert_ok``: lo que
pasa por ``error_codes`` entra en el corpus del diferencial V0/V1, y la V1
no conoce las lambdas. Se comprueban el CÓDIGO, la POSICIÓN y que no salga
NADA más.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import analyze  # noqa: E402


def _diagnostics(source: str) -> list:
    """``[(código, línea, columna)]`` de ``source``, en orden."""
    _, _, errors = analyze(source)
    return [(e.code, e.line, e.column) for e in errors]


def _expect(source: str, expected: list) -> None:
    got = _diagnostics(source)
    assert got == expected, f"se esperaba {expected}; se obtuvo {got}"


# cabecera de 4 líneas: 'main' en la 5, el vector 'v' en la 6 y el cuerpo
# desde la 7
HEAD = ("#import array.vector as vec\n"                                    # 1
        "fn not_bool(int ptr x) -> int { return 1; }\n"                     # 2
        "fn by_value(int x) -> bool { return true; }\n"                     # 3
        "fn is_even(int ptr x) -> bool { return x[0] % 2 == 0; }\n")       # 4


def _with_main(body: str) -> str:
    return (HEAD + "fn main() -> int {\n"                                   # 5
            "    var vec.Vector<int> v = vec.dynamic<int>(4);\n"            # 6
            + body + "\n    return 0;\n}\n")


def test_the_four_with_the_right_types_have_no_diagnostics():
    _expect(_with_main("    var bool a = v.any(is_even);\n"
                       "    var bool b = v.all(lambda (int ptr x) -> bool: x[0] > 0);\n"
                       "    var int c = v.count_if(is_even);\n"
                       "    var int d = v.find(is_even) ?? -1;"), [])


def test_a_predicate_that_does_not_return_bool_is_ast006():
    _expect(_with_main("    var bool a = v.any(not_bool);"), [("AST006", 7, 24)])


def test_a_predicate_that_takes_the_element_by_value_is_ast006():
    """El contrato es 'T ptr' (como 'filter'): un 'fn(int) -> bool' no
    entra, ni con nombre ni como lambda."""
    _expect(_with_main("    var bool b = v.all(by_value);\n"
                       "    var int c = v.count_if(lambda (int x) -> bool: x > 0);\n"
                       "    var int? d = v.find(by_value);"),
            [("AST006", 7, 24), ("AST006", 8, 28), ("AST006", 9, 25)])


def test_a_lambda_over_another_element_type_is_ast006():
    _expect("#import array.vector as vec\n"
            "fn main() -> int {\n"
            "    var vec.Vector<str> v = vec.dynamic<str>(4);\n"
            "    var bool a = v.any(lambda (int ptr x) -> bool: true);\n"
            "    return 0;\n}\n", [("AST006", 4, 24)])


def test_the_wrong_number_of_arguments_is_sem008():
    _expect(_with_main("    var bool e = v.any();\n"
                       "    var int f = v.count_if(is_even, 1);"),
            [("SEM008", 7, 18), ("SEM008", 8, 17)])


def test_find_gives_an_optional_that_must_be_unwrapped():
    """'find' es un 'int?': no se liga a un 'int' ni se suma sin '??' o
    'match'."""
    _expect(_with_main("    var int d = v.find(is_even);\n"
                       "    var int? i = v.find(is_even);\n"
                       "    var int j = i + 1;"),
            [("AST006", 7, 5), ("AST006", 9, 17)])


def test_the_four_on_elements_with_a_destructor_are_sem038():
    """Le pasan al predicado una COPIA: con un 'R' serían dos dueños."""
    _expect("#import array.vector as vec\n"                                # 1
            "struct { int id; } R;\n"                                      # 2
            "hook fn __free__(R ptr r) -> void { }\n"                      # 3
            "fn keep(R ptr r) -> bool { return true; }\n"                  # 4
            "fn main() -> int {\n"                                         # 5
            "    var vec.Vector<R> v = vec.dynamic<R>(2);\n"               # 6
            "    var bool a = v.any(keep);\n"                              # 7
            "    var bool b = v.all(keep);\n"                              # 8
            "    var int c = v.count_if(keep);\n"                          # 9
            "    var int? d = v.find(keep);\n"                             # 10
            "    return 0;\n}\n",
            [("SEM038", 7, 18), ("SEM038", 8, 18), ("SEM038", 9, 17),
             ("SEM038", 10, 18)])
