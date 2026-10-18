"""e2e: lo que el lexer y el parser aceptan ahora, ejecutado.

Los diagnosticos de los mismos arreglos (codigo, linea y columna) estan en
``negative_tests/test_diagnostics_lexing_parsing.py``.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import assert_output  # noqa: E402

WRITE = "fn __write__(str s) -> void;\n"


def test_literals_inside_an_interpolation_are_literals():
    assert_output(WRITE + 'fn main() -> int { '
                  "__write__(f\"[{'}'}] [{\"a\"}] [{f\"<{1 + 1}>\"}] [{\"x\" + \"}\"}]\\n\"); "
                  "return 0; }",
                  '[}] [a] [<2>] [x}]')


def test_exponent_literals_are_floats_and_match_parse_float():
    assert_output('const text = #import text;\n' + WRITE +
                  'fn main() -> int { var float a = 2.5e-3; '
                  'var float b = text.parse_float("2.5e-3"); '
                  '__write__(f"{a == b} {1e3} {-1E+2} '
                  '{1e300 == text.parse_float("1e300")}\\n"); return 0; }',
                  "true 1000.0 -100.0 true")


def test_an_optional_function_declared_without_var_runs():
    assert_output(WRITE + "fn doble(int x) -> int { return x * 2; }\n"
                  "fn main() -> int { (fn(int) -> int)? h = null; "
                  "__write__(f\"{h == null}\\n\"); h = doble; "
                  "__write__(f\"{h(4)}\\n\"); return 0; }",
                  "true\n8")
