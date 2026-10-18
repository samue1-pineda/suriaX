"""e2e/print variadico — ``print(a, b, c)`` (decision del mantenedor, H02).

Escribe cada argumento separado por UN espacio, sin salto de linea al final
(como el ``print`` de un argumento). Cada argumento cumple ``Print``. La
semantica lo descompone en ``print`` de un argumento: el HIR no cambia, el
interprete lo ejecuta como siempre, la VM lo rechaza con ``VM005`` (un
``print`` de primitivo) y el web lo traduce como antes.

Los argumentos se evaluan y escriben EN ORDEN: si uno lanza, los anteriores
ya se escribieron.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import run_source  # noqa: E402


def _run(source: str) -> str:
    code, out, err = run_source(source, args=["--run", "interpreter"])
    assert code == 0, (code, out, err)
    lines = [l for l in out.splitlines()
             if not l.startswith(("frontend OK", "HIR (", "  unidad '"))]
    return "\n".join(lines)


def test_variadic_print_separates_by_one_space_without_newline():
    out = _run("fn main() -> int {\n"
               "    var int n = 42;\n"
               "    print(\"total:\", n, 1.5, true, 'c');\n"
               "    print(\"|\");\n"
               "    return 0;\n}\n")
    assert out.endswith("total: 42 1.5 true c|"), repr(out)


def test_variadic_print_uses_print_hooks():
    out = _run("struct { int x; } P;\n"
               "hook fn __print__(P ptr p) -> void { print(\"P\", p.x); }\n"
               "fn main() -> int {\n"
               "    print(P{ x: 3 }, \"y\", 7);\n"
               "    return 0;\n}\n")
    assert out.endswith("P 3 y 7"), repr(out)


def test_variadic_print_at_top_level_and_in_a_lambda():
    """En modo script (sentencia suelta) y como cuerpo CORTO de una lambda
    'void' (el parser lo deja como una sentencia de expresion)."""
    out = _run("fn each(int n, fn(int) -> void f) -> void { f(n); }\n"
               "print(\"a\", 1);\n"
               "each(5, lambda (int x) -> void: print(\"-\", x));\n"
               "each(6, lambda (int x) -> void { print(\"+\", x); });\n")
    assert out.endswith("a 1- 5+ 6"), repr(out)


def test_variadic_print_evaluates_in_order():
    out = _run("fn f() -> int { print(\"[f]\"); return 1; }\n"
               "fn main() -> int {\n"
               "    print(\"x\", f());\n"
               "    return 0;\n}\n")
    assert out.endswith("x [f]1"), repr(out)
