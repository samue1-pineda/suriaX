"""e2e/test_runner — ``--test``: cada prueba aislada y un solo canal.

Decisión del mantenedor: cada prueba corre con sus globales RECIÉN iniciadas
(el resultado no depende del orden) y los aciertos y los fallos salen por el
MISMO canal, en orden. El código de salida no cambia (1 si alguna falla).
Las globales de cada prueba mueren al terminarla (antes, una vez al final de
la corrida), con la regla de ``run``: también tras un ``RT``.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import run_project, run_source  # noqa: E402

_PROGRESS = ("frontend OK", "HIR (", "  unidad '")

_R = ("#from io #import stdp\n"
      "struct { int id; } R;\n"
      "hook fn __free__(R ptr r) -> void { stdp.println(f\"free {r.id}\"); }\n")


def _lines(out: str) -> list:
    """La salida estándar sin las líneas de progreso del compilador."""
    return [l for l in out.splitlines() if l and not l.startswith(_PROGRESS)]


def test_each_test_gets_fresh_globals():
    """Antes la segunda prueba veía la global que cambió la primera."""
    code, out, err = run_source(
        "var int counter = 0;\n"
        'test "a" { counter = counter + 1; expect (counter == 1); }\n'
        'test "b" { counter = counter + 1; expect (counter == 1); }\n'
        "fn main() -> int { return 0; }\n", args=["--test"])
    assert code == 0, (code, out, err)
    assert _lines(out) == ["  PASS  a", "  PASS  b", "tests: 2 pasaron, 0 fallaron"]


def test_library_globals_are_fresh_too():
    """También las de las librerías: se vuelve a correr su nivel de módulo."""
    files = {
        "lib/contador.libsrx": ("var int total = 0;\n"
                                "fn sube() -> int { total = total + 1; return total; }\n"
                                "#export as contador\n"),
        "main.srcx": ("#import contador\n"
                      'test "uno" { expect (contador.sube() == 1); }\n'
                      'test "dos" { expect (contador.sube() == 1); }\n'
                      "fn main() -> int { return 0; }\n"),
    }
    code, out, err = run_project(files, args=["--test"])
    assert code == 0, (code, out, err)
    assert "  PASS  uno" in out and "  PASS  dos" in out, out


def test_passes_and_failures_share_one_channel_in_order():
    """Un FAIL salía por la salida de error y un PASS por la estándar: en una
    tubería se desordenaban respecto de lo que escribe la prueba."""
    code, out, err = run_source(
        "#from io #import stdp\n"
        'test "first" { stdp.println("in first"); expect (1 == 2); }\n'
        'test "second" { stdp.println("in second"); expect (true); }\n'
        "fn main() -> int { return 0; }\n", args=["--test"])
    assert code == 1, (code, out, err)
    lines = _lines(out)
    assert lines[0] == "in first" and lines[1].startswith("  FAIL  first"), lines
    assert lines[2:] == ["in second", "  PASS  second", "tests: 1 pasaron, 1 fallaron"], lines
    assert "FAIL" not in err and "PASS" not in err, err


def test_globals_die_at_the_end_of_each_test():
    """Antes morían una sola vez, al final de toda la corrida."""
    code, out, err = run_source(_R + (
        "var R g = R{ id: 1 };\n"
        'test "one" { expect (g.id == 1); }\n'
        'test "two" { expect (g.id == 2); }\n'
        "fn main() -> int { return 0; }\n"), args=["--test"])
    assert code == 1, (code, out, err)
    lines = _lines(out)
    assert lines[0] == "free 1" and lines[1] == "  PASS  one", lines
    assert lines[2] == "free 1" and lines[3].startswith("  FAIL  two"), lines
    assert lines[4:] == ["tests: 1 pasaron, 1 fallaron"], lines


def test_a_runtime_error_in_a_test_destroys_its_globals_too():
    """Un ``RT`` desenrolla todo (la regla de ``run``): la global de la
    prueba rota muere antes de su resultado, y la siguiente prueba empieza con
    las suyas."""
    code, out, err = run_source(_R + (
        "#import array.vector as vec\n"
        "var R g = R{ id: 1 };\n"
        'test "broken" {\n'
        "    var vec.Vector<R> v = vec.dynamic<R>(2);\n"
        "    v.push(R{ id: 5 });\n"
        "    var R ptr p = v.at(0);\n"
        "    v.set(0, R{ id: 6 });\n"
        "    expect (p.id == 6);\n"
        "}\n"
        'test "next" { expect (g.id == 1); }\n'
        "fn main() -> int { return 0; }\n"), args=["--test"])
    assert code == 1, (code, out, err)
    lines = _lines(out)
    broken = [l for l in lines if l.startswith("  FAIL  broken")]
    assert broken and "RT003" in broken[0], lines
    # la global de la prueba rota murió ANTES de su resultado, después de
    # los locales; la de 'next' también
    assert lines[:lines.index(broken[0])] == ["free 5", "free 6", "free 1"], lines
    after_broken = lines[lines.index(broken[0]) + 1:]
    assert after_broken == ["free 1", "  PASS  next", "tests: 1 pasaron, 1 fallaron"], lines


def test_a_global_that_fails_to_start_fails_each_test():
    code, out, err = run_source(
        "fn arranca() -> int { throw 9; }\n"
        "var int g = arranca();\n"
        'test "a" { expect (g == 1); }\n'
        'test "b" { expect (true); }\n'
        "fn main() -> int { return 0; }\n", args=["--test"])
    assert code == 1, (code, out, err)
    fails = [l for l in _lines(out) if l.startswith("  FAIL")]
    assert len(fails) == 2 and all("al iniciar los globales" in l and "throw 9" in l
                                   for l in fails), fails
