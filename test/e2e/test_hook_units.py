"""e2e/hook_units — un hook se ejecuta con el cuerpo de SU unidad.

La tabla de hooks del programa principal trae también los de sus librerías,
con la línea de su archivo. El intérprete buscaba el cuerpo por (nombre,
línea) empezando por el programa: un hook de librería en la MISMA línea que
uno del programa ejecutaba el del programa. Igual con ``__cast__``.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import run_project  # noqa: E402

_W = "fn __write__(str s) -> void;\n"


def _program_output(out: str) -> str:
    return "".join(l + "\n" for l in out.splitlines()
                   if not l.startswith(("frontend OK", "HIR (", "  unidad '")))


def test_a_library_hook_on_the_same_line_runs_its_own_body():
    files = {
        # '__print__' en la línea 2 de los DOS archivos
        "lib/cosa.libsrx": (_W +
                            "hook fn __print__(Caja ptr c) -> void { __write__(\"lib-caja\"); }\n"
                            "struct { int n; } Caja;\n"
                            "#export as cosa\n"),
        "main.srcx": (_W +
                      "hook fn __print__(Mia ptr c) -> void { __write__(\"main-mia\"); }\n"
                      "struct { int n; } Mia;\n"
                      "#import cosa\n"
                      "fn main() -> int {\n"
                      "    var cosa.Caja c = cosa.Caja{ n: 1 };\n"
                      "    var Mia m = Mia{ n: 2 };\n"
                      "    print(c); __write__(\" \"); print(m); __write__(\"\\n\");\n"
                      "    return 0;\n"
                      "}\n"),
    }
    code, out, err = run_project(files, args=["--run", "interpreter"])
    assert code == 0, (code, out, err)
    assert _program_output(out) == "lib-caja main-mia\n", out


def test_a_library_cast_on_the_same_line_runs_its_own_body():
    files = {
        "lib/cosa.libsrx": ("struct { int n; } Caja;\n"
                            "hook fn __cast__(Caja c) -> int { return 100; }\n"
                            "#export as cosa\n"),
        "main.srcx": ("struct { int n; } Mia;\n"
                      "hook fn __cast__(Mia m) -> int { return 7; }\n"
                      "#import cosa\n"
                      "#from io #import stdp\n"
                      "fn main() -> int {\n"
                      "    var cosa.Caja c = cosa.Caja{ n: 1 };\n"
                      "    var Mia m = Mia{ n: 2 };\n"
                      "    stdp.println(f\"{cast<int>(c)} {cast<int>(m)}\");\n"
                      "    return 0;\n"
                      "}\n"),
    }
    code, out, err = run_project(files, args=["--run", "interpreter"])
    assert code == 0, (code, out, err)
    assert _program_output(out) == "100 7\n", out
