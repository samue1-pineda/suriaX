"""e2e/vector_functional — 'Vector.sort_by', 'Vector.filter', el paquete
'func' ('map', 'fold') y los índices de 'Vector' fuera de [0, len).

El comportamiento se pasa como una función con nombre: del módulo, de una
librería ('lib.f') o un método ('Tipo.metodo'). Cada elemento llega como
puntero ('T ptr'). Los argumentos de tipo de 'func' se escriben
('func.map<int, str>(&v, f)').

Se comprueba la SALIDA EXACTA del intérprete ('--run interpreter').
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import run_project, run_source  # noqa: E402

HEAD = ("#from io #import stdp\n"
        "#import array.vector as vec\n"
        "#import func\n")

# imprime un Vector<int> en una línea: '[3 1 2]'
SHOW = ("fn show(vec.Vector<int> ptr v) -> void {\n"
        "    var str s = \"[\";\n"
        "    var int i = 0;\n"
        "    while (i < v.len()) {\n"
        "        if (i > 0) { s = s + \" \"; }\n"
        "        s = s + f\"{v.get(i)}\";\n"
        "        i = i + 1;\n"
        "    }\n"
        "    stdp.println(s + \"]\");\n"
        "}\n")

PERSON = ("struct { str name; int age; } Person;\n"
          "@impl Person {\n"
          "    fn compare_age(Person ptr self, Person ptr other) -> int {\n"
          "        return self.age - other.age;\n"
          "    }\n"
          "    fn is_adult(Person ptr self) -> bool { return self.age >= 18; }\n"
          "    fn name_of(Person ptr self) -> str { return self.name; }\n"
          "}\n"
          "fn people() -> vec.Vector<Person> {\n"
          "    var vec.Vector<Person> ps = vec.dynamic<Person>(2);\n"
          "    ps.push(Person{ name: \"ana\", age: 30 });\n"
          "    ps.push(Person{ name: \"luis\", age: 12 });\n"
          "    ps.push(Person{ name: \"eva\", age: 30 });\n"
          "    ps.push(Person{ name: \"bob\", age: 12 });\n"
          "    ps.push(Person{ name: \"zoe\", age: 7 });\n"
          "    return ps;\n"
          "}\n"
          "fn names(vec.Vector<Person> ptr ps) -> void {\n"
          "    var str s = \"\";\n"
          "    var int i = 0;\n"
          "    while (i < ps.len()) { s = s + ps.at(i).name + \" \"; i = i + 1; }\n"
          "    stdp.println(s);\n"
          "}\n")


def _clean(out: str) -> str:
    lines = [l for l in out.splitlines()
             if not l.startswith(("frontend OK", "HIR (", "  unidad '"))]
    return "\n".join(lines) + ("\n" if lines else "")


def _output(source: str, expected: str, *, exit_code: int = 0) -> str:
    code, out, err = run_source(source, args=["--run", "interpreter"])
    got = _clean(out)
    assert code == exit_code, (
        f"exit {code}, se esperaba {exit_code}\nstdout: {out!r}\nstderr: {err!r}")
    assert got == expected, (
        f"salida distinta.\n  esperada: {expected!r}\n  obtenida: {got!r}\n"
        f"  stderr: {err!r}")
    return err


def _main(body: str, before: str = "") -> str:
    return HEAD + SHOW + before + "fn main() -> int {\n" + body + \
        "\n    return 0;\n}\n"


def _ints(name: str, values) -> str:
    """Declara 'name' como Vector<int> dinámico con 'values'."""
    pushes = "".join(f"    {name}.push({x});\n" for x in values)
    return f"    var vec.Vector<int> {name} = vec.dynamic<int>(2);\n" + pushes


# --------------------------------------------------------------------------- #
# sort_by
# --------------------------------------------------------------------------- #

def test_sort_by_orders_with_the_given_function():
    _output(_main(_ints("v", [3, 8, 1, 6, 5]) +
                  "    v.sort_by(descending);\n    show(&v);\n"
                  "    v.sort_by(ascending);\n    show(&v);",
                  before="fn descending(int ptr a, int ptr b) -> int { return b[0] - a[0]; }\n"
                         "fn ascending(int ptr a, int ptr b) -> int { return a[0] - b[0]; }\n"),
            "[8 6 5 3 1]\n[1 3 5 6 8]\n")


def test_sort_by_edge_cases():
    """Vacío, uno solo, todos iguales y ya ordenado al revés."""
    _output(_main("    var vec.Vector<int> a = vec.make<int>(4);\n"
                  "    a.sort_by(ascending); show(&a);\n" +
                  _ints("b", [7]) + "    b.sort_by(ascending); show(&b);\n" +
                  _ints("c", [4, 4, 4]) + "    c.sort_by(ascending); show(&c);\n" +
                  _ints("d", [5, 4, 3, 2, 1]) + "    d.sort_by(ascending); show(&d);",
                  before="fn ascending(int ptr a, int ptr b) -> int { return a[0] - b[0]; }\n"),
            "[]\n[7]\n[4 4 4]\n[1 2 3 4 5]\n")


def test_sort_by_many_elements_leaves_every_pair_in_order():
    """37 elementos pseudoaleatorios (no potencia de 2: tramos desparejos)."""
    _output(_main("    var vec.Vector<int> v = vec.dynamic<int>(4);\n"
                  "    var int x = 7;\n"
                  "    var int i = 0;\n"
                  "    while (i < 37) { x = (x * 31 + 11) % 101; v.push(x); i = i + 1; }\n"
                  "    v.sort_by(descending);\n"
                  "    var bool ok = true;\n"
                  "    i = 1;\n"
                  "    while (i < v.len()) { if (v.get(i - 1) < v.get(i)) { ok = false; } i = i + 1; }\n"
                  "    stdp.println(f\"{v.len()} {ok} {v.get(0)} {v.get(36)}\");",
                  before="fn descending(int ptr a, int ptr b) -> int { return b[0] - a[0]; }\n"),
            "37 true 99 2\n")


def test_sort_by_is_stable_and_takes_a_method():
    """'Person.compare_age' es un 'fn(Person ptr, Person ptr) -> int'. Los
    que empatan (30 y 12) conservan su orden de llegada."""
    _output(HEAD + PERSON + "fn main() -> int {\n"
            "    var vec.Vector<Person> ps = people();\n"
            "    ps.sort_by(Person.compare_age);\n"
            "    names(&ps);\n"
            "    return 0;\n}\n",
            "zoe luis bob ana eva \n")


def test_sort_by_moves_elements_with_a_destructor_without_copying():
    """Ningún '__free__' durante el orden: cada elemento se destruye una vez,
    al morir el vector (que suelta sus celdas de la última a la primera)."""
    _output(HEAD +
            "struct { int id; } R;\n"
            "hook fn __free__(R ptr r) -> void { stdp.println(f\"free {r.id}\"); }\n"
            "fn by_id(R ptr a, R ptr b) -> int { return a.id - b.id; }\n"
            "fn scope() -> void {\n"
            "    var vec.Vector<R> v = vec.dynamic<R>(2);\n"
            "    v.push(R{ id: 3 }); v.push(R{ id: 1 }); v.push(R{ id: 2 });\n"
            "    v.sort_by(by_id);\n"
            "    stdp.println(f\"sorted {v.at(0).id}{v.at(1).id}{v.at(2).id}\");\n"
            "}\n"
            "fn main() -> int {\n"
            "    scope();\n"
            "    stdp.println(\"end\");\n"
            "    return 0;\n}\n",
            "sorted 123\nfree 3\nfree 2\nfree 1\nend\n")


def test_a_generic_passes_its_comparison_down():
    _output(_main(_ints("v", [2, 9, 4]) +
                  "    sorted<int>(&v, descending);\n    show(&v);",
                  before="fn descending(int ptr a, int ptr b) -> int { return b[0] - a[0]; }\n"
                         "fn sorted<T>(vec.Vector<T> ptr mutable v, fn(T ptr, T ptr) -> int c) -> void {\n"
                         "    v.sort_by(c);\n"
                         "}\n"),
            "[9 4 2]\n")


# --------------------------------------------------------------------------- #
# filter
# --------------------------------------------------------------------------- #

def test_filter_copies_the_ones_that_pass_and_leaves_the_original():
    _output(_main("    var vec.Vector<int> v = vec.make<int>(8);\n"
                  "    v.push(3); v.push(8); v.push(1); v.push(6);\n"
                  "    var vec.Vector<int> e = v.filter(is_even);\n"
                  "    show(&e); show(&v);\n"
                  "    var vec.Vector<int> none = v.filter(is_big);\n"
                  "    show(&none);\n"
                  # el nuevo crece aunque el original sea de capacidad fija
                  "    stdp.println(f\"{v.fixed()} {e.fixed()} {e.cap()}\");\n"
                  "    var int i = 0;\n"
                  "    while (i < 10) { e.push(i); i = i + 1; }\n"
                  "    stdp.println(f\"{e.len()}\");",
                  before="fn is_even(int ptr x) -> bool { return x[0] % 2 == 0; }\n"
                         "fn is_big(int ptr x) -> bool { return x[0] > 100; }\n"),
            "[8 6]\n[3 8 1 6]\n[]\ntrue false 8\n12\n")


def test_filter_takes_a_method_and_the_copies_are_independent():
    _output(HEAD + PERSON + "fn main() -> int {\n"
            "    var vec.Vector<Person> ps = people();\n"
            "    var vec.Vector<Person> adults = ps.filter(Person.is_adult);\n"
            "    adults.at_mut(0).name = \"ANA\";\n"
            "    names(&adults);\n"
            "    names(&ps);\n"
            "    return 0;\n}\n",
            "ANA eva \nana luis eva bob zoe \n")


# --------------------------------------------------------------------------- #
# func.map y func.fold
# --------------------------------------------------------------------------- #

def test_map_builds_a_vector_of_another_type():
    _output(_main(_ints("v", [1, 2, 3]) +
                  "    var vec.Vector<str> m = func.map<int, str>(&v, label);\n"
                  "    stdp.println(f\"{m.get(0)}{m.get(1)}{m.get(2)} {m.len()}\");\n"
                  "    var vec.Vector<int> d = func.map<int, int>(&v, twice);\n"
                  "    show(&d); show(&v);\n"
                  "    var vec.Vector<int> e = vec.dynamic<int>(1);\n"
                  "    stdp.println(f\"{func.map<int, str>(&e, label).len()}\");",
                  before="fn label(int ptr x) -> str { return f\"<{x[0]}>\"; }\n"
                         "fn twice(int ptr x) -> int { return x[0] * 2; }\n"),
            "<1><2><3> 3\n[2 4 6]\n[1 2 3]\n0\n")


def test_map_takes_a_method():
    _output(HEAD + PERSON + "fn main() -> int {\n"
            "    var vec.Vector<Person> ps = people();\n"
            "    var vec.Vector<str> ns = func.map<Person, str>(&ps, Person.name_of);\n"
            "    stdp.println(f\"{ns.get(0)} {ns.get(4)} {ns.len()}\");\n"
            "    return 0;\n}\n",
            "ana zoe 5\n")


def test_fold_reduces_left_to_right():
    _output(_main(_ints("v", [1, 2, 3, 4]) +
                  "    stdp.println(f\"{func.fold<int, int>(&v, 0, add)}\");\n"
                  "    stdp.println(func.fold<int, str>(&v, \">\", join));\n"
                  "    var vec.Vector<int> e = vec.dynamic<int>(1);\n"
                  "    stdp.println(f\"{func.fold<int, int>(&e, 42, add)}\");",
                  before="fn add(int acc, int ptr x) -> int { return acc + x[0]; }\n"
                         "fn join(str acc, int ptr x) -> str { return acc + f\"{x[0]}\"; }\n"),
            "10\n>1234\n42\n")


def test_fold_moves_an_accumulator_with_a_destructor():
    """Cada acumulador intermedio se destruye una vez, cuando 'grow' lo
    reemplaza; el último es de quien llama."""
    _output(HEAD +
            "struct { int id; } R;\n"
            "hook fn __free__(R ptr r) -> void { stdp.println(f\"free {r.id}\"); }\n"
            "fn grow(R acc, int ptr x) -> R { return R{ id: acc.id + x[0] }; }\n"
            "fn wrap(int ptr x) -> R { return R{ id: x[0] * 10 }; }\n"
            "fn scope(vec.Vector<int> ptr v) -> void {\n"
            "    var R total = func.fold<int, R>(v, R{ id: 100 }, grow);\n"
            "    stdp.println(f\"total {total.id}\");\n"
            "    var vec.Vector<R> rs = func.map<int, R>(v, wrap);\n"
            "    stdp.println(f\"map {rs.at(0).id} {rs.at(1).id}\");\n"
            "}\n"
            "fn main() -> int {\n"
            "    var vec.Vector<int> v = vec.dynamic<int>(4);\n"
            "    v.push(1); v.push(2);\n"
            "    scope(&v);\n"
            "    stdp.println(\"end\");\n"
            "    return 0;\n}\n",
            "free 100\nfree 101\ntotal 103\nmap 10 20\nfree 20\nfree 10\nfree 103\nend\n")


def test_library_functions_are_values_for_all_four():
    """Una función de OTRA unidad ('order.descending') como argumento."""
    files = {
        "order.libsrx": (
            "public fn descending(int ptr a, int ptr b) -> int { return b[0] - a[0]; }\n"
            "public fn is_odd(int ptr x) -> bool { return x[0] % 2 != 0; }\n"
            "public fn twice(int ptr x) -> int { return x[0] * 2; }\n"
            "public fn add(int acc, int ptr x) -> int { return acc + x[0]; }\n"
            "#export as order\n"),
        "main.srcx": (
            HEAD + "#import order\n"
            "fn main() -> int {\n"
            "    var vec.Vector<int> v = vec.dynamic<int>(4);\n"
            "    v.push(2); v.push(5); v.push(3);\n"
            "    v.sort_by(order.descending);\n"
            "    var vec.Vector<int> o = v.filter(order.is_odd);\n"
            "    var vec.Vector<int> d = func.map<int, int>(&v, order.twice);\n"
            "    var int s = func.fold<int, int>(&v, 0, order.add);\n"
            "    stdp.println(f\"{v.get(0)}{v.get(1)}{v.get(2)} {o.get(0)}{o.get(1)} "
            "{d.get(0)}{d.get(2)} {s}\");\n"
            "    return 0;\n}\n"),
    }
    code, out, err = run_project(files, args=["--run", "interpreter"])
    assert code == 0, err
    assert _clean(out) == "532 53 104 10\n", (out, err)


# --------------------------------------------------------------------------- #
# índices fuera de [0, len) aunque quepan en la capacidad
# --------------------------------------------------------------------------- #

def test_indexes_between_len_and_cap_are_out_of_range():
    """Antes 'v.get(2)' y 'v[2]' con len 1 y cap 4 daban 'null', y 'v[2] = x'
    guardaba un elemento que 'len' no contaba. Ahora las cuatro operaciones
    lanzan 'excepciones.IndiceFueraDeRango', que se atrapa."""
    body = ("    var vec.Vector<int> v = vec.make<int>(4);\n"
            "    v.push(1);\n"
            "    try { var int a = v.get(2); } catch (exc.IndiceFueraDeRango e) { stdp.println(e.mensaje); };\n"
            "    try { var int b = v[3]; } catch (exc.IndiceFueraDeRango e) { stdp.println(e.mensaje); };\n"
            "    try { v[1] = 5; } catch (exc.IndiceFueraDeRango e) { stdp.println(e.mensaje); };\n"
            "    try { v.set(1, 5); } catch (exc.IndiceFueraDeRango e) { stdp.println(e.mensaje); };\n"
            "    try { var int c = v.get(-1); } catch (exc.IndiceFueraDeRango e) { stdp.println(e.mensaje); };\n"
            "    try { var int d = v.get(9); } catch (exc.IndiceFueraDeRango e) { stdp.println(e.mensaje); };\n"
            "    v[0] = 7;\n"
            "    v.set(0, v.get(0) + 1);\n"
            "    stdp.println(f\"{v[0]} {v.len()} {v.cap()}\");")
    _output(HEAD + "#import excepciones as exc\nfn main() -> int {\n" + body +
            "\n    return 0;\n}\n",
            "índice 2 fuera de rango [0, 1)\n"
            "índice 3 fuera de rango [0, 1)\n"
            "índice 1 fuera de rango [0, 1)\n"
            "índice 1 fuera de rango [0, 1)\n"
            "índice -1 fuera de rango [0, 1)\n"
            "índice 9 fuera de rango [0, 1)\n"
            "8 1 4\n")


def test_an_uncaught_out_of_range_get_stops_the_program():
    err = _output(HEAD + "fn main() -> int {\n"
                  "    var vec.Vector<int> v = vec.make<int>(4);\n"
                  "    v.push(1);\n"
                  "    stdp.println(\"before\");\n"
                  "    stdp.println(f\"{v.get(1)}\");\n"
                  "    return 0;\n}\n", "before\n", exit_code=70)
    # el 'IndiceFueraDeRango' de 'Vector' sale como el del runtime: EXC002,
    # con la línea de la llamada del programa (H03)
    assert "EXC002: índice 1 fuera de rango [0, 1) (8:21)" in err, err
