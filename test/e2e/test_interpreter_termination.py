"""e2e/interpreter_termination — cómo termina un programa en el intérprete.

- Un error que nadie atrapa (``throw``, ``EXCxxx`` o un ``RT``) ya
  desenrolló la pila y destruyó los locales, y ahora destruye también las
  globales (antes no: un ``File`` global no se volcaba). Decisión del
  mantenedor: un ``RT`` también, no es un ``std::abort``.
- Un error de ejecución dentro de una LIBRERÍA dice su archivo: antes salía
  ``RT020: throw ... (102:30)`` con una línea de otro archivo.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import run_project, run_source  # noqa: E402

_V0 = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "V0", "main.py")

_PROGRESS = ("frontend OK", "HIR (", "  unidad '")

_R = ("#from io #import stdp\n"
      "struct { int id; } R;\n"
      "hook fn __free__(R ptr r) -> void { stdp.println(f\"free {r.id}\"); }\n")


def _run(source: str) -> tuple:
    code, out, err = run_source(source, args=["--run", "interpreter"])
    return code, "".join(l + "\n" for l in out.splitlines()
                         if not l.startswith(_PROGRESS)), err


# --------------------------------------------------------------------------- #
# globales al terminar con un error
# --------------------------------------------------------------------------- #

def test_an_uncaught_throw_destroys_globals_after_the_locals():
    code, out, err = _run(_R + """\
var R g = R{ id: 1 };
fn main() -> int {
    var R l = R{ id: 10 };
    throw "fallo";
}
""")
    assert code == 70, (code, out, err)
    assert out == "free 10\nfree 1\n", out
    assert "RT020" in err, err


def test_an_uncaught_program_exception_destroys_globals():
    code, out, err = _run(_R + """\
var R g = R{ id: 1 };
fn main() -> int {
    var int zero = 0;
    return 1 / zero;
}
""")
    assert code == 70, (code, out, err)
    assert out == "free 1\n", out
    assert "EXC001" in err, err


def test_a_runtime_error_destroys_globals_too():
    """Un ``RT`` desenrolla todo, como un ``throw`` sin atrapar: los locales
    y después las globales (decisión del mantenedor)."""
    code, out, err = _run(_R + """\
#import array.vector as vec
var R g = R{ id: 1 };
fn main() -> int {
    var vec.Vector<R> v = vec.dynamic<R>(2);
    v.push(R{ id: 5 });
    var R ptr p = v.at(0);
    v.set(0, R{ id: 6 });
    stdp.println(f"{p.id}");
    return 0;
}
""")
    assert code == 70, (code, out, err)
    assert "RT003" in err, err
    lines = [l for l in out.splitlines() if l.startswith("free")]
    assert lines == ["free 5", "free 6", "free 1"], out


def test_a_global_file_is_written_after_an_uncaught_throw():
    """El caso de la caza: el ``__free__`` del ``File`` global (que vuelca y
    cierra) no corría si el programa terminaba con un error sin atrapar."""
    fuente = ("#import sistema.archivos as arch\n"
              "var arch.File log = arch.open(\"salida.txt\", \"w\");\n"
              "fn main() -> int { log.write(\"antes del fallo\\n\"); throw 1; }\n")
    with tempfile.TemporaryDirectory(prefix="suriax-test-") as tmp:
        ruta = os.path.join(tmp, "prog.srcx")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(fuente)
        proc = subprocess.run([sys.executable, _V0, ruta, "--run", "interpreter"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", cwd=tmp, timeout=120)
        assert proc.returncode == 70, proc.stderr
        with open(os.path.join(tmp, "salida.txt"), encoding="utf-8") as fh:
            assert fh.read() == "antes del fallo\n"


# --------------------------------------------------------------------------- #
# el archivo de un error de ejecución
# --------------------------------------------------------------------------- #

_LIB = {
    "lib/falla.libsrx": ("fn lanza(int n) -> void {\n"
                         "    throw n;\n"
                         "}\n"
                         "fn divide(int a, int b) -> int {\n"
                         "    return a / b;\n"
                         "}\n"
                         "#export as falla\n"),
}


def test_a_throw_in_a_library_names_its_file():
    code, out, err = run_project({**_LIB, "main.srcx": (
        "#import falla\n"
        "fn main() -> int {\n"
        "    falla.lanza(7);\n"
        "    return 0;\n"
        "}\n")}, args=["--run", "interpreter"])
    assert code == 70, (code, out, err)
    assert "RT020: throw 7 (lib/falla.libsrx:2:5)" in err, err


def test_a_program_exception_in_a_library_names_its_file():
    code, out, err = run_project({**_LIB, "main.srcx": (
        "#import falla\n"
        "fn main() -> int {\n"
        "    var int c = 0;\n"
        "    return falla.divide(1, c);\n"
        "}\n")}, args=["--run", "interpreter"])
    assert code == 70, (code, out, err)
    assert "EXC001: división por cero (lib/falla.libsrx:5:12)" in err, err


def test_an_error_in_the_program_keeps_the_short_position():
    """El programa principal sigue sin archivo, como sus errores al compilar:
    el usuario sabe qué ejecutó."""
    code, out, err = run_project({**_LIB, "main.srcx": (
        "#import falla\n"
        "fn main() -> int {\n"
        "    throw 3;\n"
        "}\n")}, args=["--run", "interpreter"])
    assert code == 70, (code, out, err)
    assert "RT020: throw 3 (3:5)" in err, err


def test_a_stdlib_throw_names_the_program_call():
    """Un ``throw`` de la stdlib sin atrapar nombra la LLAMADA del programa
    (``v.at_mut(5)``, línea 6), no una línea de ``<stdlib>/array/vector.libsrx``
    que no le dice nada a quien llamó (H03). Una librería del PROYECTO sí
    nombra su archivo: ver ``test_a_throw_in_a_library_names_its_file``."""
    code, out, err = _run(
        "#import array.vector as vec\n"
        "struct { int n; } Caja;\n"
        "fn main() -> int {\n"
        "    var vec.Vector<Caja> v = vec.dynamic<Caja>(2);\n"
        "    v.push(Caja{ n: 1 });\n"
        "    var Caja ptr mutable p = v.at_mut(5);\n"
        "    return 0;\n"
        "}\n")
    assert code == 70, (code, out, err)
    assert "RT020: throw at_mut fuera de rango (6:30)" in err, err
    assert "<stdlib>" not in err, err
