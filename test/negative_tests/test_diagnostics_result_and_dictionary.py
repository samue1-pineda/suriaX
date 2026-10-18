"""negative_tests/diagnostics: 'result.Result<T, E>', 'Dictionary.get_or',
'Dictionary.items()' y 'collections.pair.Pair<K, V>'.

- ``Result`` es un enum genérico: sin sus argumentos de tipo (o con otro
  número) es ``SEM027``; dos instancias distintas no se mezclan
  (``AST006``); un ``match`` sin ``Err`` es ``SEM030``.
- ``get_or`` y ``unwrap_or`` comprueban el tipo del ``default``
  (``AST006``); ``items()`` da un ``Vector<Pair<K, V>>`` exacto.
- Lo que COPIA un valor con destructor (``get_or``, ``items``,
  ``unwrap_or``) es ``SEM038`` en la llamada; ligar un ``Pair`` o un
  ``Result`` que posee un recurso a otro nombre es ``SEM032``.

Va por ``analyze`` y no por ``helpers.error_codes``/``assert_ok``: lo que
pasa por ``error_codes`` entra en el corpus del diferencial V0/V1, y la V1
no conoce los enums genéricos ni las lambdas. Se comprueban el CÓDIGO, la
POSICIÓN y que no salga NADA más.
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


# cabecera de 4 líneas; 'main' en la 5 y su cuerpo desde la 6
HEAD = ("#import array.vector as vec\n"                  # 1
        "#import collections.dictionary as dic\n"        # 2
        "#import collections.pair as pr\n"               # 3
        "#import result as res\n")                       # 4


def _main(body: str) -> str:
    return HEAD + "fn main() -> int {\n" + body + "\n    return 0;\n}\n"


# --------------------------------------------------------------------------- #
# lo válido no da nada
# --------------------------------------------------------------------------- #

def test_the_valid_uses_have_no_diagnostics():
    _expect(_main("    var res.Result<int, str> a = res.Result<int, str>.Ok(5);\n"
                  "    var bool ok = a.is_ok();\n"
                  "    var int n = a.unwrap_or(0);\n"
                  "    var dic.Dictionary<str, int> m = dic.make<str, int>(4);\n"
                  "    var int g = m.get_or(\"k\", 0);\n"
                  "    var vec.Vector<pr.Pair<str, int>> it = m.items();\n"
                  "    var pr.Pair<str, int> p = pr.Pair<str, int>{ key: \"k\", value: 1 };"),
            [])


# --------------------------------------------------------------------------- #
# Result
# --------------------------------------------------------------------------- #

def test_a_variant_without_its_type_arguments_is_sem027():
    _expect(_main("    var res.Result<int, str> a = res.Result.Ok(5);"),
            [("SEM027", 6, 34)])


def test_a_result_with_one_type_argument_is_sem027():
    _expect(_main("    var res.Result<int> d = res.Result<int, str>.Ok(1);"),
            [("SEM027", 6, 5), ("AST006", 6, 5)])


def test_two_instances_do_not_mix_and_the_payload_has_its_type():
    _expect(_main("    var res.Result<int, str> b = res.Result<str, int>.Ok(\"x\");\n"
                  "    var res.Result<int, str> c = res.Result<int, str>.Ok(\"x\");"),
            [("AST006", 6, 5), ("AST006", 7, 58)])


def test_a_result_is_not_its_value():
    """Sin desenvolver no se suma."""
    _expect(_main("    var res.Result<int, str> a = res.Result<int, str>.Ok(5);\n"
                  "    var int f = 1 + a;"),
            [("AST006", 7, 17)])


def test_a_match_without_err_is_sem030():
    _expect(_main("    var res.Result<int, str> a = res.Result<int, str>.Ok(5);\n"
                  "    match (a) {\n"
                  "        case res.Result<int, str>.Ok(v) { }\n"
                  "    };"),
            [("SEM030", 7, 5)])


def test_unwrap_or_and_is_ok_check_their_arguments():
    _expect(_main("    var res.Result<int, str> a = res.Result<int, str>.Ok(5);\n"
                  "    var int e = a.unwrap_or(\"0\");\n"
                  "    var bool g = a.is_ok(1);"),
            [("AST006", 7, 29), ("SEM008", 8, 18)])


# --------------------------------------------------------------------------- #
# Dictionary.get_or / items, Pair
# --------------------------------------------------------------------------- #

def test_get_or_checks_the_key_the_default_and_the_result():
    _expect(_main("    var dic.Dictionary<str, int> m = dic.make<str, int>(4);\n"
                  "    var int a = m.get_or(\"k\", \"0\");\n"
                  "    var int b = m.get_or(1, 0);\n"
                  "    var str c = m.get_or(\"k\", 0);\n"
                  "    var int f = m.get_or(\"k\");"),
            [("AST006", 7, 31), ("AST006", 8, 26), ("AST006", 9, 5),
             ("SEM008", 10, 17)])


def test_items_gives_exactly_a_vector_of_pairs_of_k_and_v():
    _expect(_main("    var dic.Dictionary<str, int> m = dic.make<str, int>(4);\n"
                  "    var vec.Vector<pr.Pair<int, str>> d = m.items();\n"
                  "    var vec.Vector<pr.Pair<str, int>> e = m.items(1);"),
            [("AST006", 7, 5), ("SEM008", 8, 43)])


def test_a_pair_literal_names_every_field_and_its_type_arguments():
    _expect(_main("    var pr.Pair<str, int> p = pr.Pair<str, int>{ key: \"k\" };\n"
                  "    var pr.Pair<str, int> q = pr.Pair{ key: \"k\", value: 1 };"),
            [("SEM028", 6, 31), ("SEM027", 7, 31), ("AST006", 7, 5)])


# --------------------------------------------------------------------------- #
# valores con destructor
# --------------------------------------------------------------------------- #

R_HEAD = (HEAD +
          "struct { int id; } R;\n"                                     # 5
          "hook fn __free__(R ptr r) -> void { }\n")                    # 6


def test_what_copies_a_value_with_a_destructor_is_sem038():
    """'get_or', 'items' y 'unwrap_or' COPIAN el valor guardado."""
    _expect(R_HEAD +
            "fn main() -> int {\n"                                       # 7
            "    var dic.Dictionary<int, R> m = dic.make<int, R>(2);\n"  # 8
            "    var R z = R{ id: 0 };\n"                                # 9
            "    var R g = m.get_or(1, move z);\n"                       # 10
            "    var vec.Vector<pr.Pair<int, R>> it = m.items();\n"      # 11
            "    var res.Result<R, str> r = res.Result<R, str>.Err(\"x\");\n"  # 12
            "    var R u = r.unwrap_or(R{ id: 1 });\n"                   # 13
            "    return 0;\n}\n",
            [("SEM038", 10, 15), ("SEM038", 11, 42), ("SEM038", 13, 15)])


def test_binding_a_pair_or_result_that_owns_a_resource_is_sem032():
    _expect(R_HEAD +
            "fn main() -> int {\n"                                                     # 7
            "    var pr.Pair<str, R> p = pr.Pair<str, R>{ key: \"k\", value: R{ id: 2 } };\n"  # 8
            "    var pr.Pair<str, R> q = p;\n"                                         # 9
            "    var res.Result<R, str> r = res.Result<R, str>.Ok(R{ id: 3 });\n"      # 10
            "    var res.Result<R, str> s = r;\n"                                      # 11
            "    return 0;\n}\n",
            [("SEM032", 9, 5), ("SEM032", 11, 5)])
