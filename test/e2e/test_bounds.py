"""e2e/bounds — cotas, deducción y métodos genéricos ejecutados (paso 4).

Lo que la Semántica comprobó contra una COTA y no contra un tipo se
despacha al ejecutar con el tipo de la instancia: ``print(x)`` con
``T: Print`` (el ``__print__`` del tipo, o el texto de un primitivo) y
``x.metodo()`` con un trait de las cotas de ``T`` (un dunder o un método de
``@impl``). La deducción y los métodos genéricos no cambian el HIR.

Son del INTÉRPRETE: la VM rechaza el despacho por cota con ``VM003``
(``backend/test_backend_cpp_bounds.py``) y el target web no representa
valores de tipo ``T``.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import run_source  # noqa: E402

PRELUDE = "#from io #import stdp\n"


def _run(before: str, body: str, expected: str) -> None:
    code, out, err = run_source(
        PRELUDE + before + "fn main() -> int {\n" + body + "\n    return 0;\n}\n",
        args=["--run", "interpreter"])
    assert code == 0 and expected in out, (
        f"salida esperada no encontrada (salida {code}).\n"
        f"  esperado: {expected!r}\n  stdout:   {out!r}\n  stderr:   {err!r}")


SHAPES = ("@trait struct {\n"
          "    fn area(self ptr s) -> int;\n"
          "    dunder fn __name__(self ptr) -> str;\n"
          "} Shape;\n"
          "@impl(Shape) struct { int r; } Circle;\n"
          "@impl Circle { fn area(Circle ptr self) -> int { return self.r * self.r * 3; } }\n"
          "dunder fn __name__(Circle ptr c) -> str { return \"circle\"; }\n"
          "@impl(Shape) struct { int l; } Square;\n"
          "@impl Square { fn area(Square ptr self) -> int { return self.l * self.l; } }\n"
          "dunder fn __name__(Square ptr c) -> str { return \"square\"; }\n"
          "fn describe<T: Shape>(T ptr x) -> str { return f\"{x.__name__()}={x.area()}\"; }\n"
          "fn by_value<T: Shape>(T x) -> int { return x.area(); }\n")


def test_trait_methods_dispatch_on_the_instance_type():
    _run(SHAPES,
         "    var Circle c = Circle{ r: 2 };\n"
         "    var Square s = Square{ l: 3 };\n"
         "    stdp.println(f\"{describe(&c)} {describe(&s)} {by_value(c)} {by_value(s)}\");",
         "circle=12 square=9 12 9")


def test_print_bound_uses_the_hook_or_the_primitive_text():
    _run("struct { int n; } P;\n"
         "hook fn __print__(P ptr p) -> void { stdp.print(f\"P<{p.n}>\"); }\n"
         "fn show<T: Print>(T x) -> void { print(x); stdp.print(\"|\"); }\n",
         "    show(P{ n: 7 });\n    show(42);\n    show(\"hola\");\n"
         "    show(2.5);\n    show(true);\n    stdp.println(\"\");",
         "P<7>|42|hola|2.5|true|")


def test_deduced_type_arguments_run_like_written_ones():
    _run("#import array.vector as vec\n#import func\n"
         "fn label(int ptr x) -> str { return f\"<{x[0]}>\"; }\n"
         "fn add(int acc, int ptr x) -> int { return acc + x[0]; }\n"
         "fn smaller<T: Ord>(T a, T b) -> T { if (a < b) { return a; } return b; }\n",
         "    var vec.Vector<int> v = vec.dynamic<int>(4);\n"
         "    v.push(1); v.push(2); v.push(3);\n"
         "    var vec.Vector<str> a = func.map(&v, label);\n"
         "    var vec.Vector<str> b = func.map<int, str>(&v, label);\n"
         "    stdp.println(f\"{a.get(0)}{b.get(2)} {func.fold(&v, 0, add)} "
         "{smaller(3, 9)} {smaller(\"b\", \"a\")}\");",
         "<1><3> 6 3 a")


def test_generic_method_changes_the_element_type():
    _run("struct { T v; } Box<T>;\n"
         "@impl Box<T> {\n"
         "    fn map<U>(Box<T> ptr self, fn(T) -> U f) -> Box<U> { return Box<U>{ v: f(self.v) }; }\n"
         "}\n"
         "fn twice(int x) -> str { return f\"{x * 2}\"; }\n",
         "    var Box<int> b = Box<int>{ v: 21 };\n"
         "    var Box<str> s = b.map(twice);\n"
         "    var Box<str> t = b.map<str>(twice);\n"
         "    stdp.println(f\"{s.v} {t.v}\");",
         "42 42")


def test_vector_sort_with_the_ord_bound_still_sorts():
    _run("#import array.vector as vec\n",
         "    var vec.Vector<int> v = vec.dynamic<int>(4);\n"
         "    v.push(3); v.push(1); v.push(2);\n"
         "    v.sort();\n"
         "    stdp.println(f\"{v.get(0)}{v.get(1)}{v.get(2)}\");",
         "123")
