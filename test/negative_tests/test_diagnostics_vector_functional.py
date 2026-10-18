"""negative_tests/diagnostics: 'sort_by', 'filter', 'func.map', 'func.fold'
y los ARGUMENTOS de una llamada a un método.

Antes, ``x.metodo(args)`` solo comprobaba la propiedad (``move``): ni la
aridad ni el tipo de cada argumento. ``v.push("hola")`` sobre un
``Vector<int>``, ``v.push(1, 2)`` o ``v.sort_by(f)`` con una ``f`` de otro
tipo compilaban y fallaban (o no) al ejecutar. Ahora es ``SEM008`` (aridad)
y ``AST006`` (tipo), como en una llamada a una función.

Lo que COPIA un elemento con destructor ('filter', y hoy 'func.map' y
'func.fold', que le pasan a 'f' una copia) es ``SEM038`` en la llamada.

Se comprueban el CÓDIGO y la POSICIÓN (línea, columna), nunca el texto.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import analyze, assert_ok  # noqa: E402


def _diagnostics(source: str) -> list:
    """``[(código, línea, columna)]`` de ``source``, en orden."""
    _, _, errors = analyze(source)
    return [(e.code, e.line, e.column) for e in errors]


def _expect(source: str, expected: list) -> None:
    got = _diagnostics(source)
    assert got == expected, f"se esperaba {expected}; se obtuvo {got}"


# cabecera de 8 líneas: el cuerpo de 'main' empieza en la línea 10
HEAD = ("#import array.vector as vec\n"                                   # 1
        "#import func\n"                                                  # 2
        "fn by_value(int a, int b) -> int { return a - b; }\n"            # 3
        "fn descending(int ptr a, int ptr b) -> int { return b[0] - a[0]; }\n"  # 4
        "fn is_even(int ptr x) -> bool { return x[0] % 2 == 0; }\n"      # 5
        "fn not_bool(int ptr x) -> int { return 1; }\n"                   # 6
        "fn label(int ptr x) -> str { return \"x\"; }\n"                  # 7
        "fn add(int acc, int ptr x) -> int { return acc + x[0]; }\n")     # 8


def _with_main(body: str, before: str = "") -> str:
    """``HEAD`` + ``before`` + un ``main`` cuyo cuerpo empieza en la línea
    10 (si ``before`` no ocupa líneas) con un ``Vector<int> v`` ya
    declarado en la línea 10."""
    return (HEAD + before + "fn main() -> int {\n"
            "    var vec.Vector<int> v = vec.dynamic<int>(4);\n"
            + body + "\n    return 0;\n}\n")


# --------------------------------------------------------------------------- #
# lo válido compila (sin falsos positivos)
# --------------------------------------------------------------------------- #

def test_the_four_with_the_right_types_compile():
    assert_ok(_with_main(
        "    v.sort_by(descending);\n"
        "    var vec.Vector<int> e = v.filter(is_even);\n"
        "    var vec.Vector<str> m = func.map<int, str>(&v, label);\n"
        "    var int s = func.fold<int, int>(&v, 0, add);"))


def test_a_generic_body_passes_its_function_to_sort_by():
    assert_ok(HEAD +
              "fn sorted<T>(vec.Vector<T> ptr mutable v, fn(T ptr, T ptr) -> int c) -> void {\n"
              "    v.sort_by(c);\n"
              "}\n"
              "fn main() -> int {\n"
              "    var vec.Vector<int> v = vec.dynamic<int>(4);\n"
              "    sorted<int>(&v, descending);\n"
              "    return 0;\n}\n")


def test_sort_by_moves_elements_with_a_destructor_so_it_compiles():
    """'sort_by' no copia: con un 'R' con destructor compila."""
    assert_ok("#import array.vector as vec\n"
              "struct { int id; } R;\n"
              "hook fn __free__(R ptr r) -> void { }\n"
              "fn by_id(R ptr a, R ptr b) -> int { return a.id - b.id; }\n"
              "fn main() -> int {\n"
              "    var vec.Vector<R> v = vec.dynamic<R>(2);\n"
              "    v.sort_by(by_id);\n"
              "    return 0;\n}\n")


# --------------------------------------------------------------------------- #
# sort_by y filter: el tipo de la función
# --------------------------------------------------------------------------- #

def test_sort_by_with_a_comparison_by_value_is_ast006():
    """La comparación recibe PUNTEROS: un 'fn(int, int) -> int' no encaja."""
    _expect(_with_main("    v.sort_by(by_value);"), [("AST006", 11, 15)])


def test_sort_by_with_something_that_is_not_a_function_is_ast006():
    _expect(_with_main("    v.sort_by(3);"), [("AST006", 11, 15)])
    _expect(_with_main("    v.sort_by(null);"), [("AST006", 11, 15)])


def test_filter_with_a_predicate_that_does_not_return_bool_is_ast006():
    _expect(_with_main("    var vec.Vector<int> w = v.filter(not_bool);"),
            [("AST006", 11, 38)])


def test_sort_by_and_filter_take_exactly_one_argument():
    _expect(_with_main("    v.sort_by();"), [("SEM008", 11, 5)])
    _expect(_with_main("    var vec.Vector<int> w = v.filter(is_even, 2);"),
            [("SEM008", 11, 29)])


def test_a_generic_function_is_not_a_comparison():
    """Una genérica no es un valor (SEM044): se envuelve en una con los
    tipos escritos."""
    _expect(_with_main("    v.sort_by(any_order);",
                       before="fn any_order<T>(T ptr a, T ptr b) -> int { return 0; }\n"),
            [("SEM044", 12, 15)])


def test_filter_on_elements_with_a_destructor_is_sem038():
    """'filter' COPIA los que se quedan: con un 'R' serían dos dueños."""
    _expect("#import array.vector as vec\n"
            "struct { int id; } R;\n"
            "hook fn __free__(R ptr r) -> void { }\n"
            "fn keep(R ptr r) -> bool { return true; }\n"
            "fn main() -> int {\n"
            "    var vec.Vector<R> v = vec.dynamic<R>(2);\n"
            "    var vec.Vector<R> w = v.filter(keep);\n"
            "    return 0;\n}\n", [("SEM038", 7, 27)])


# --------------------------------------------------------------------------- #
# func.map y func.fold
# --------------------------------------------------------------------------- #

def test_map_with_a_function_of_another_type_is_ast006():
    """'map<int, int>' pide un 'fn(int ptr) -> int'; 'label' da 'str'."""
    _expect(_with_main("    var vec.Vector<int> m = func.map<int, int>(&v, label);"),
            [("AST006", 11, 52)])


def test_fold_with_the_wrong_initial_value_or_function_is_ast006():
    _expect(_with_main("    var int s = func.fold<int, int>(&v, \"0\", add);"),
            [("AST006", 11, 41)])
    _expect(_with_main("    var int s = func.fold<int, int>(&v, 0, label);"),
            [("AST006", 11, 44)])


def test_map_and_fold_on_elements_with_a_destructor_are_sem038():
    """Hoy 'f' recibe un puntero a una COPIA del elemento ('&' sobre un
    escalar de un bloque es RT011), y la copia de un 'R' son dos dueños."""
    _expect("#import array.vector as vec\n"
            "#import func\n"
            "struct { int id; } R;\n"
            "hook fn __free__(R ptr r) -> void { }\n"
            "fn id_of(R ptr r) -> int { return r.id; }\n"
            "fn sum(int acc, R ptr r) -> int { return acc + r.id; }\n"
            "fn main() -> int {\n"
            "    var vec.Vector<R> v = vec.dynamic<R>(2);\n"
            "    var vec.Vector<int> ids = func.map<R, int>(&v, id_of);\n"
            "    var int s = func.fold<R, int>(&v, 0, sum);\n"
            "    return 0;\n}\n", [("SEM038", 9, 31), ("SEM038", 10, 17)])


# --------------------------------------------------------------------------- #
# los argumentos de cualquier llamada a un método
# --------------------------------------------------------------------------- #

def test_a_method_argument_of_the_wrong_type_is_ast006():
    """Antes compilaba y era un ICE000 del intérprete al comparar."""
    _expect(_with_main("    v.push(\"hola\");\n"
                       "    var int g = v.get(\"a\");"),
            [("AST006", 11, 12), ("AST006", 12, 23)])


def test_a_method_call_with_the_wrong_arity_is_sem008():
    _expect(_with_main("    v.push(1, 2);"), [("SEM008", 11, 5)])


def test_a_method_of_a_plain_struct_checks_its_arguments_too():
    _expect("struct { int x; } Box;\n"
            "@impl Box {\n"
            "    fn apply(Box ptr self, fn(int) -> int f) -> int { return f(self.x); }\n"
            "}\n"
            "fn main() -> int {\n"
            "    var Box b = Box{ x: 1 };\n"
            "    var int r = b.apply(3);\n"
            "    var int q = b.apply();\n"
            "    return 0;\n}\n", [("AST006", 7, 25), ("SEM008", 8, 17)])
