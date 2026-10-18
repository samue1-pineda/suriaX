"""e2e/result_and_dictionary_items — 'result.Result<T, E>', 'Dictionary.get_or',
'Dictionary.items()' y 'collections.pair.Pair<K, V>'.

- ``Result<T, E>`` es un enum genérico (``Ok(T)``, ``Err(E)``) con los tipos
  siempre escritos, que se abre con ``match``; ``is_ok`` y ``unwrap_or``
  son sus dos ayudas.
- ``d.get_or(k, default)`` da una copia del valor o ``default``, sin
  agregar la clave.
- ``d.items()`` da un ``Vector<Pair<K, V>>`` con COPIAS, en el orden de
  ``keys()``.

Se comprueba la SALIDA EXACTA del intérprete (``--run interpreter``; la VM
rechaza los enums genéricos con ``VM002`` y los valores función con
``VM001``). Va por ``run_source`` y no por ``helpers.assert_ok``: la V1 no
conoce las lambdas.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import run_source  # noqa: E402

HEAD = ("#from io #import stdp\n"
        "#import array.vector as vec\n"
        "#import collections.dictionary as dic\n"
        "#import collections.pair as pr\n"
        "#import result as res\n")


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


def _main(body: str, before: str = "") -> str:
    return HEAD + before + "fn main() -> int {\n" + body + "    return 0;\n}\n"


DIVIDE = ("fn divide(int a, int b) -> res.Result<int, str> {\n"
          "    if (b == 0) { return res.Result<int, str>.Err(\"division by zero\"); }\n"
          "    return res.Result<int, str>.Ok(a / b);\n"
          "}\n"
          "fn show(res.Result<int, str> r) -> str {\n"
          "    match (r) {\n"
          "        case res.Result<int, str>.Ok(v) { return f\"ok {v}\"; }\n"
          "        case res.Result<int, str>.Err(m) { return f\"error: {m}\"; }\n"
          "    };\n"
          "    return \"?\";\n"
          "}\n")


# --------------------------------------------------------------------------- #
# Result
# --------------------------------------------------------------------------- #

def test_a_function_that_can_fail_returns_ok_or_err_and_match_opens_it():
    _output(_main("    stdp.println(show(divide(10, 2)));\n"
                  "    stdp.println(show(divide(1, 0)));\n", before=DIVIDE),
            "ok 5\nerror: division by zero\n")


def test_is_ok_and_unwrap_or():
    _output(_main("    var res.Result<int, str> a = divide(9, 3);\n"
                  "    var res.Result<int, str> b = divide(9, 0);\n"
                  "    stdp.println(f\"{a.is_ok()} {b.is_ok()} {a.unwrap_or(-1)} {b.unwrap_or(-1)}\");\n",
                  before=DIVIDE),
            "true false 3 -1\n")


def test_unwrap_or_does_not_change_the_result():
    _output(_main("    var res.Result<int, str> a = divide(8, 2);\n"
                  "    var int x = a.unwrap_or(0);\n"
                  "    stdp.println(f\"{x} {show(a)} {a.is_ok()}\");\n", before=DIVIDE),
            "4 ok 4 true\n")


def test_an_f_string_writes_the_variant_and_its_payload():
    _output(_main("    stdp.println(f\"{divide(6, 3)} {divide(6, 0)}\");\n", before=DIVIDE),
            "Ok(2) Err(division by zero)\n")


def test_the_type_can_be_imported_by_name():
    _output("#from io #import stdp\n"
            "#from result #import Result\n"
            "fn main() -> int {\n"
            "    var Result<str, int> r = Result<str, int>.Err(404);\n"
            "    var Result<str, int> s = Result<str, int>.Ok(\"fine\");\n"
            "    stdp.println(f\"{r} {r.unwrap_or(\"none\")} {s.unwrap_or(\"none\")}\");\n"
            "    return 0;\n}\n",
            "Err(404) none fine\n")


def test_payloads_can_be_structs_and_enums():
    _output(_main("    var res.Result<P, Why> a = res.Result<P, Why>.Ok(P{ x: 1, y: 2 });\n"
                  "    var res.Result<P, Why> b = res.Result<P, Why>.Err(Why.TooBig);\n"
                  "    match (b) {\n"
                  "        case res.Result<P, Why>.Ok(p) { stdp.println(f\"{p.x}\"); }\n"
                  "        case res.Result<P, Why>.Err(w) { stdp.println(f\"{w}\"); }\n"
                  "    };\n"
                  "    stdp.println(f\"{a.unwrap_or(P{ x: 0, y: 0 }).y} {b.unwrap_or(P{ x: 7, y: 8 }).y}\");\n",
                  before="struct { int x; int y; } P;\n"
                         "enum Why { TooBig, TooSmall };\n"),
            "TooBig\n2 8\n")


def test_results_in_a_vector_are_counted_with_a_predicate():
    """'Result' y los predicados juntos: cuántos fallaron."""
    _output(_main("    var vec.Vector<res.Result<int, str>> all = vec.dynamic<res.Result<int, str>>(3);\n"
                  "    all.push(divide(4, 2));\n"
                  "    all.push(divide(4, 0));\n"
                  "    all.push(divide(9, 3));\n"
                  "    var int ok = all.count_if(lambda (res.Result<int, str> ptr r) -> bool: r.is_ok());\n"
                  "    stdp.println(f\"{ok} {all.find(lambda (res.Result<int, str> ptr r) -> bool: not r.is_ok()) ?? -1}\");\n",
                  before=DIVIDE),
            "2 1\n")


# --------------------------------------------------------------------------- #
# Dictionary.get_or
# --------------------------------------------------------------------------- #

def test_get_or_gives_the_value_or_the_default():
    _output(_main("    var dic.Dictionary<str, int> d = dic.make<str, int>(4);\n"
                  "    d.put(\"a\", 1);\n"
                  "    d.put(\"b\", 0);\n"
                  "    stdp.println(f\"{d.get_or(\"a\", 9)} {d.get_or(\"b\", 9)} {d.get_or(\"z\", 9)}\");\n"),
            "1 0 9\n")


def test_get_or_does_not_add_the_key():
    _output(_main("    var dic.Dictionary<str, int> d = dic.make<str, int>(4);\n"
                  "    d.put(\"a\", 1);\n"
                  "    var int x = d.get_or(\"z\", 5);\n"
                  "    stdp.println(f\"{x} {d.len()} {d.contains(\"z\")}\");\n"),
            "5 1 false\n")


def test_get_or_gives_a_copy():
    """Cambiar lo que da 'get_or' no toca el diccionario (como 'get')."""
    _output(_main("    var dic.Dictionary<int, P> d = dic.make<int, P>(4);\n"
                  "    d.put(1, P{ n: 10 });\n"
                  "    var P p = d.get_or(1, P{ n: 0 });\n"
                  "    p.n = 99;\n"
                  "    stdp.println(f\"{p.n} {d.get(1).n}\");\n",
                  before="struct { int n; } P;\n"),
            "99 10\n")


def test_get_or_counts_words():
    _output(_main("    var dic.Dictionary<str, int> counts = dic.make<str, int>(4);\n"
                  "    var vec.Vector<str> words = vec.dynamic<str>(6);\n"
                  "    words.push(\"to\"); words.push(\"be\"); words.push(\"or\");\n"
                  "    words.push(\"not\"); words.push(\"to\"); words.push(\"be\");\n"
                  "    var int i = 0;\n"
                  "    while (i < words.len()) {\n"
                  "        var str w = words.get(i);\n"
                  "        counts.put(w, counts.get_or(w, 0) + 1);\n"
                  "        i = i + 1;\n"
                  "    }\n"
                  "    stdp.println(f\"{counts.len()} {counts.get(\"to\")} {counts.get(\"be\")} {counts.get(\"or\")} {counts.get(\"not\")}\");\n"),
            "4 2 2 1 1\n")


def test_get_or_after_remove_gives_the_default():
    _output(_main("    var dic.Dictionary<int, str> d = dic.make<int, str>(4);\n"
                  "    d.put(7, \"seven\");\n"
                  "    var bool gone = d.remove(7);\n"
                  "    stdp.println(f\"{gone} {d.get_or(7, \"none\")}\");\n"),
            "true none\n")


# --------------------------------------------------------------------------- #
# Dictionary.items y Pair
# --------------------------------------------------------------------------- #

def test_items_follows_the_order_of_keys_and_values():
    """Mismo largo y, posición a posición, la misma clave que 'keys()' y el
    mismo valor que 'values()'. Con 20 claves el diccionario crece."""
    _output(_main("    var dic.Dictionary<int, int> d = dic.make<int, int>(2);\n"
                  "    var int i = 0;\n"
                  "    while (i < 20) { d.put(i * 7, i); i = i + 1; }\n"
                  "    var vec.Vector<int> ks = d.keys();\n"
                  "    var vec.Vector<int> vs = d.values();\n"
                  "    var vec.Vector<pr.Pair<int, int>> it = d.items();\n"
                  "    var bool same = it.len() == ks.len();\n"
                  "    var int j = 0;\n"
                  "    while (j < it.len()) {\n"
                  "        var pr.Pair<int, int> p = it.get(j);\n"
                  "        if (p.key != ks.get(j) or p.value != vs.get(j) or p.key != p.value * 7) { same = false; }\n"
                  "        j = j + 1;\n"
                  "    }\n"
                  "    stdp.println(f\"{it.len()} {same}\");\n"),
            "20 true\n")


def test_items_sees_every_slot_including_the_first():
    """Con un '__hash__' constante 0, las tres claves caen en las casillas
    0, 1 y 2 (sondeo lineal): 'items()' tiene que ver las tres, también la
    de la casilla 0. Con claves 'int' la casilla depende de splitmix64 y
    ninguna prueba la fijaba."""
    _output(_main("    var dic.Dictionary<K, int> d = dic.make<K, int>(4);\n"
                  "    d.put(K{ n: 1 }, 10);\n"
                  "    d.put(K{ n: 2 }, 20);\n"
                  "    d.put(K{ n: 3 }, 30);\n"
                  "    var vec.Vector<pr.Pair<K, int>> it = d.items();\n"
                  "    stdp.println(f\"{it.len()} {it.get(0).key.n}={it.get(0).value} "
                  "{it.get(2).key.n}={it.get(2).value}\");\n",
                  before="struct { int n; } K;\n"
                         "hook fn __hash__(K ptr k) -> int { return 0; }\n"),
            "3 1=10 3=30\n")


def test_items_are_copies():
    """Cambiar un par del vector no toca el diccionario."""
    _output(_main("    var dic.Dictionary<str, int> d = dic.make<str, int>(4);\n"
                  "    d.put(\"a\", 1);\n"
                  "    var vec.Vector<pr.Pair<str, int>> it = d.items();\n"
                  "    it.at_mut(0).value = 50;\n"
                  "    stdp.println(f\"{it.get(0).value} {d.get(\"a\")}\");\n"),
            "50 1\n")


def test_items_of_an_empty_dictionary_and_after_remove():
    _output(_main("    var dic.Dictionary<str, int> d = dic.make<str, int>(4);\n"
                  "    var int before = d.items().len();\n"
                  "    d.put(\"a\", 1);\n"
                  "    d.put(\"b\", 2);\n"
                  "    var bool r = d.remove(\"a\");\n"
                  "    var vec.Vector<pr.Pair<str, int>> it = d.items();\n"
                  "    stdp.println(f\"{before} {it.len()} {it.get(0)}\");\n"),
            "0 1 Pair{key: \"b\", value: 2}\n")


def test_items_sorted_by_value_with_a_lambda():
    """Contar y ordenar de mayor a menor (empates por la clave)."""
    _output(_main("    var dic.Dictionary<str, int> d = dic.make<str, int>(8);\n"
                  "    d.put(\"x\", 3); d.put(\"y\", 1); d.put(\"z\", 3); d.put(\"w\", 2);\n"
                  "    var vec.Vector<pr.Pair<str, int>> it = d.items();\n"
                  "    it.sort_by(lambda (pr.Pair<str, int> ptr a, pr.Pair<str, int> ptr b) -> int {\n"
                  "        if (a.value != b.value) { return b.value - a.value; }\n"
                  "        if (a.key < b.key) { return -1; }\n"
                  "        return 1;\n"
                  "    });\n"
                  "    var int i = 0;\n"
                  "    while (i < it.len()) {\n"
                  "        stdp.println(f\"{it.get(i).key}={it.get(i).value}\");\n"
                  "        i = i + 1;\n"
                  "    }\n"),
            "x=3\nz=3\nw=2\ny=1\n")


def test_a_pair_is_a_plain_generic_struct():
    _output(_main("    var pr.Pair<str, int> a = pr.Pair<str, int>{ key: \"k\", value: 1 };\n"
                  "    var pr.Pair<str, int> b = a;\n"
                  "    b.value = 2;\n"
                  "    var pr.Pair<str, int> c = pr.Pair<str, int>{ key: \"k\", value: 1 };\n"
                  "    stdp.println(f\"{a} {b.value} {a == c} {a == b}\");\n"),
            "Pair{key: \"k\", value: 1} 2 true false\n")


def test_returning_a_borrowed_case_binding_from_a_generic_copies_it():
    """Regresion: en un generico, 'return v' con 'v' ligado por un 'case'
    sobre un PUNTERO cedia el payload y dejaba al sujeto en 'null'
    ('4 Ok(null)'), aun con T = int. Lo prestado se devuelve copiado."""
    _output(_main("    var res.Result<int, str> a = res.Result<int, str>.Ok(4);\n"
                  "    var int x = first(&a, 0);\n"
                  "    stdp.println(f\"{x} {a}\");\n",
                  "fn first<T, E>(res.Result<T, E> ptr r, T d) -> T {\n"
                  "    match (r) {\n"
                  "        case res.Result<T, E>.Ok(v) { return v; }\n"
                  "        case res.Result<T, E>.Err(m) { }\n"
                  "    };\n"
                  "    return d;\n"
                  "}\n"),
            "4 Ok(4)\n")
