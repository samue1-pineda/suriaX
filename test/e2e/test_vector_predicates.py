"""e2e/vector_predicates — 'any', 'all', 'count_if' y 'find' de 'Vector'.

Preguntan por los elementos con un predicado ``fn(T ptr) -> bool`` (una
función con nombre o una lambda). 'any', 'all' y 'find' se detienen en
cuanto saben la respuesta; 'count_if' los recorre todos; 'find' da el
índice del primero que cumple como un ``int?`` (``null`` si ninguno).
Ninguna cambia el vector.

Las llamadas al predicado se CUENTAN con una global: una global no es una
captura (cualquier función la puede asignar), así que una función con
nombre puede contar cuántas veces la llamaron. Es lo que comprueba que
cortan donde dicen.

Se comprueba la SALIDA EXACTA del intérprete (``--run interpreter``). Va
por ``run_source`` y no por ``helpers.assert_ok``: la V1 no conoce las
lambdas.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import run_source  # noqa: E402

HEAD = ("#from io #import stdp\n"
        "#import array.vector as vec\n"
        "var int calls = 0;\n"
        "fn is_even(int ptr x) -> bool { calls = calls + 1; return x[0] % 2 == 0; }\n"
        "fn positive(int ptr x) -> bool { calls = calls + 1; return x[0] > 0; }\n")


def _output(source: str, expected: str, *, exit_code: int = 0) -> str:
    code, out, err = run_source(source, args=["--run", "interpreter"])
    lines = [l for l in out.splitlines()
             if not l.startswith(("frontend OK", "HIR (", "  unidad '"))]
    got = "\n".join(lines) + ("\n" if lines else "")
    assert code == exit_code, (
        f"exit {code}, se esperaba {exit_code}\nstdout: {out!r}\nstderr: {err!r}")
    assert got == expected, (
        f"salida distinta.\n  esperada: {expected!r}\n  obtenida: {got!r}\n"
        f"  stderr: {err!r}")
    return err


def _ints(name: str, values, *, fixed: bool = False) -> str:
    maker = "make" if fixed else "dynamic"
    text = f"    var vec.Vector<int> {name} = vec.{maker}<int>({max(len(values), 1)});\n"
    return text + "".join(f"    {name}.push({v});\n" for v in values)


def _main(body: str, before: str = "") -> str:
    return HEAD + before + "fn main() -> int {\n" + body + "    return 0;\n}\n"


# --------------------------------------------------------------------------- #
# any
# --------------------------------------------------------------------------- #

def test_any_is_true_and_stops_at_the_first_match():
    """[3, 4, 5, 6]: el primero par es el 4 (segundo): 2 llamadas, no 4."""
    _output(_main(_ints("v", [3, 4, 5, 6]) +
                  "    var bool r = v.any(is_even);\n"
                  "    stdp.println(f\"{r} {calls}\");\n"),
            "true 2\n")


def test_any_is_false_when_none_matches_and_asks_every_element():
    _output(_main(_ints("v", [1, 3, 5]) +
                  "    var bool r = v.any(is_even);\n"
                  "    stdp.println(f\"{r} {calls}\");\n"),
            "false 3\n")


def test_any_on_an_empty_vector_is_false_without_calling():
    _output(_main(_ints("v", []) +
                  "    var bool r = v.any(is_even);\n"
                  "    stdp.println(f\"{r} {calls}\");\n"),
            "false 0\n")


def test_any_with_a_lambda_that_reads_a_capture():
    _output(_main(_ints("v", [1, 7, 2]) +
                  "    var int limit = 6;\n"
                  "    var bool over = v.any(lambda (int ptr x) -> bool: x[0] > limit);\n"
                  "    limit = 7;\n"
                  "    var bool still = v.any(lambda (int ptr x) -> bool: x[0] > limit);\n"
                  "    stdp.println(f\"{over} {still}\");\n"),
            "true false\n")


# --------------------------------------------------------------------------- #
# all
# --------------------------------------------------------------------------- #

def test_all_is_true_when_every_element_matches():
    _output(_main(_ints("v", [2, 4, 6]) +
                  "    var bool r = v.all(is_even);\n"
                  "    stdp.println(f\"{r} {calls}\");\n"),
            "true 3\n")


def test_all_is_false_and_stops_at_the_first_failure():
    """[2, 3, 4, 6]: el 3 (segundo) no es par: 2 llamadas."""
    _output(_main(_ints("v", [2, 3, 4, 6]) +
                  "    var bool r = v.all(is_even);\n"
                  "    stdp.println(f\"{r} {calls}\");\n"),
            "false 2\n")


def test_all_on_an_empty_vector_is_true_without_calling():
    _output(_main(_ints("v", []) +
                  "    var bool r = v.all(is_even);\n"
                  "    stdp.println(f\"{r} {calls}\");\n"),
            "true 0\n")


def test_all_and_any_disagree_on_a_mixed_vector():
    _output(_main(_ints("v", [-1, 2]) +
                  "    stdp.println(f\"{v.all(positive)} {v.any(positive)}\");\n"),
            "false true\n")


# --------------------------------------------------------------------------- #
# count_if
# --------------------------------------------------------------------------- #

def test_count_if_counts_and_asks_every_element():
    _output(_main(_ints("v", [1, 2, 3, 4, 6, 7]) +
                  "    var int n = v.count_if(is_even);\n"
                  "    stdp.println(f\"{n} {calls}\");\n"),
            "3 6\n")


def test_count_if_is_zero_on_an_empty_vector_and_when_none_matches():
    _output(_main(_ints("v", []) + _ints("w", [1, 3]) +
                  "    stdp.println(f\"{v.count_if(is_even)} {w.count_if(is_even)}\");\n"),
            "0 0\n")


def test_count_if_counts_all_when_all_match():
    _output(_main(_ints("v", [5, 5, 5]) +
                  "    stdp.println(f\"{v.count_if(lambda (int ptr x) -> bool: x[0] == 5)}\");\n"),
            "3\n")


# --------------------------------------------------------------------------- #
# find
# --------------------------------------------------------------------------- #

def test_find_gives_the_index_of_the_first_match_and_stops_there():
    """Hay dos pares (índices 1 y 3): 'find' da el 1 tras 2 llamadas."""
    _output(_main(_ints("v", [3, 4, 5, 6]) +
                  "    var int? i = v.find(is_even);\n"
                  "    stdp.println(f\"{i ?? -1} {calls}\");\n"),
            "1 2\n")


def test_find_gives_index_zero_when_the_first_matches():
    _output(_main(_ints("v", [8, 1]) +
                  "    stdp.println(f\"{v.find(is_even) ?? -1} {calls}\");\n"),
            "0 1\n")


def test_find_gives_the_last_index_when_only_the_last_matches():
    _output(_main(_ints("v", [1, 3, 5, 10]) +
                  "    stdp.println(f\"{v.find(is_even) ?? -1}\");\n"),
            "3\n")


def test_find_gives_null_when_none_matches_and_on_an_empty_vector():
    _output(_main(_ints("v", [1, 3]) + _ints("e", []) +
                  "    match (v.find(is_even)) {\n"
                  "        case null { stdp.println(\"none\"); }\n"
                  "        case i { stdp.println(f\"at {i}\"); }\n"
                  "    };\n"
                  "    stdp.println(f\"{e.find(is_even) ?? -1} {calls}\");\n"),
            "none\n-1 2\n")


def test_find_result_is_an_int_that_indexes_the_vector():
    """El índice que da 'find' sirve para leer el elemento ('get')."""
    _output(_main(_ints("v", [10, 25, 30]) +
                  "    match (v.find(lambda (int ptr x) -> bool: x[0] > 20)) {\n"
                  "        case null { stdp.println(\"none\"); }\n"
                  "        case i { stdp.println(f\"{i} {v.get(i)}\"); }\n"
                  "    };\n"),
            "1 25\n")


# --------------------------------------------------------------------------- #
# otros tipos de elemento, vectores fijos, el vector no cambia
# --------------------------------------------------------------------------- #

def test_predicates_on_structs_read_fields_through_the_pointer():
    _output(_main("    var vec.Vector<P> v = vec.dynamic<P>(3);\n"
                  "    v.push(P{ name: \"ana\", age: 30 });\n"
                  "    v.push(P{ name: \"bea\", age: 17 });\n"
                  "    v.push(P{ name: \"cris\", age: 45 });\n"
                  "    var int adult = 18;\n"
                  "    stdp.println(f\"{v.all(lambda (P ptr p) -> bool: p.age >= adult)} "
                  "{v.count_if(lambda (P ptr p) -> bool: p.age >= adult)} "
                  "{v.find(lambda (P ptr p) -> bool: p.name == \"cris\") ?? -1}\");\n",
                  before="struct { str name; int age; } P;\n"),
            "false 2 2\n")


def test_predicates_on_strings_with_a_named_function():
    _output(_main("    var vec.Vector<str> v = vec.dynamic<str>(3);\n"
                  "    v.push(\"a\");\n"
                  "    v.push(\"bb\");\n"
                  "    v.push(\"ccc\");\n"
                  "    stdp.println(f\"{v.any(long_word)} {v.count_if(long_word)} {v.find(long_word) ?? -1}\");\n",
                  before="fn long_word(str ptr s) -> bool { return len(s[0]) > 1; }\n"),
            "true 2 1\n")


def test_predicates_work_on_a_fixed_capacity_vector():
    """'make' (capacidad fija) con espacio sin usar: solo cuentan los
    elementos, no las celdas reservadas."""
    _output(_main("    var vec.Vector<int> v = vec.make<int>(5);\n"
                  "    v.push(2);\n"
                  "    v.push(4);\n"
                  "    stdp.println(f\"{v.all(is_even)} {v.count_if(is_even)} {v.find(positive) ?? -1} {calls}\");\n"),
            "true 2 0 5\n")


def test_the_vector_does_not_change():
    _output(_main(_ints("v", [4, 1, 2]) +
                  "    var bool a = v.any(is_even);\n"
                  "    var bool b = v.all(is_even);\n"
                  "    var int c = v.count_if(is_even);\n"
                  "    var int? d = v.find(is_even);\n"
                  "    stdp.println(f\"{v.len()} {v.get(0)} {v.get(1)} {v.get(2)}\");\n"),
            "3 4 1 2\n")


def test_inside_a_generic_function_the_predicate_is_passed_through():
    _output(_main(_ints("v", [1, 2, 3]) +
                  "    stdp.println(f\"{matches(&v, is_even)}\");\n",
                  before="fn matches<T>(vec.Vector<T> ptr v, fn(T ptr) -> bool p) -> str {\n"
                         "    return f\"{v.any(p)}/{v.all(p)}/{v.count_if(p)}/{v.find(p) ?? -1}\";\n"
                         "}\n"),
            "true/false/1/1\n")
