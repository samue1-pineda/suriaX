"""e2e/print de primitivos — ``print(x)`` con ``x`` un primitivo.

Decisión del mantenedor: ``print(x)`` vale con PRIMITIVOS en todas partes y
escribe el valor como lo escribe un f-string (``{x}``), sin salto de línea —
lo mismo que hacía ya dentro de un genérico con ``T: Print``. Antes, fuera
de un genérico, era ``SEM001``. ``len(3)`` sigue siendo un error (y un
puntero a un primitivo no es un primitivo: ``print(p)`` también).

El intérprete lo ejecuta; la VM lo rechaza con ``VM005`` (ver
``backend/test_backend_cpp_lambdas.py``) y el target web ya lo traducía
(``test/web/lambdas.test.ts``).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import run_source  # noqa: E402

VALUES = [("int", "-7"), ("int", "42"), ("float", "2.5"), ("float", "1e20"),
          ("float", "0.1"), ("bool", "true"), ("char", "'z'"), ("str", "\"hola\""),
          ("byte", "200")]


def _run(source: str) -> str:
    code, out, err = run_source(source, args=["--run", "interpreter"])
    assert code == 0, (code, out, err)
    lines = [l for l in out.splitlines()
             if not l.startswith(("frontend OK", "HIR (", "  unidad '"))]
    return "\n".join(lines)


def _program(statement: str, *, before: str = "") -> str:
    body = "".join(f"    var {t} v{i} = {lit};\n" for i, (t, lit) in enumerate(VALUES))
    body += "".join(statement.format(v=f"v{i}") + "\n" for i in range(len(VALUES)))
    return ("#from io #import stdp\n" + before + "fn main() -> int {\n" + body +
            "    return 0;\n}\n")


def test_print_of_a_primitive_writes_what_an_fstring_writes():
    """El mismo texto que ``{x}``, sin salto de linea, para cada primitivo."""
    printed = _run(_program("    print({v}); print(\"|\");"))
    expected = _run(_program("    stdp.print(f\"{{{v}}}\"); stdp.print(\"|\");"))
    assert printed == expected, (printed, expected)
    assert printed == "-7|42|2.5|1e+20|0.1|true|z|hola|200|", printed


def test_print_outside_a_generic_is_the_same_as_inside_one():
    generic = _run(_program("    show({v}); print(\"|\");",
                            before="fn show<T: Print>(T x) -> void { print(x); }\n"))
    direct = _run(_program("    print({v}); print(\"|\");"))
    assert generic == direct, (generic, direct)


def test_the_hir_carries_print_of_a_primitive_as_a_hook_of_the_primitive():
    """Lo implicito se ve: '--hir-pretty' dice a que despacha."""
    import tempfile
    import subprocess
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with tempfile.TemporaryDirectory(prefix="suriax-test-") as tmp:
        src = os.path.join(tmp, "prog.srcx")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write("fn main() -> int {\n    print(5);\n    return 0;\n}\n")
        out = os.path.join(tmp, "prog.txt")
        proc = subprocess.run([sys.executable, os.path.join(root, "V0", "main.py"),
                               src, "--hir-pretty", out],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", cwd=tmp, timeout=120)
        assert proc.returncode == 0, (proc.stdout, proc.stderr)
        with open(out, encoding="utf-8") as fh:
            text = fh.read()
    assert "print(5)  ⟨hook __print__ de int⟩:void" in text, text
