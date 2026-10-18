"""e2e/compiler_output — lo que dice la CLI al compilar.

- ``frontend OK: ...`` solo sale si el frontend no encontró errores: antes
  salía también con errores, justo encima de ellos.
- Un programa que se llama como una librería que importa
  (``excepciones.srcx`` con ``#import excepciones``) ya no se encuentra a sí
  mismo: la búsqueda salta el archivo que importa. Si no hay otra librería
  con ese nombre, el error lo dice.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import run_project, run_source  # noqa: E402


def test_frontend_ok_is_not_printed_with_errors():
    code, out, err = run_source("fn main() -> int { return nada; }\n")
    assert code != 0, (code, out, err)
    assert "SEM001" in out + err, (out, err)
    assert "frontend OK" not in out + err, (out, err)


def test_frontend_ok_is_not_printed_with_syntax_errors():
    code, out, err = run_source("fn main( -> int { return 0; }\n")
    assert code != 0, (code, out, err)
    assert "frontend OK" not in out + err, (out, err)


def test_frontend_ok_is_printed_without_errors():
    code, out, err = run_source("fn main() -> int { return 0; }\n")
    assert code == 0, (code, out, err)
    assert "frontend OK" in out, out


def test_a_program_named_like_a_library_imports_the_library():
    code, out, err = run_project({"excepciones.srcx": (
        "#import excepciones as exc\n"
        "#from io #import stdp\n"
        "fn main() -> int {\n"
        "    var int c = 0;\n"
        "    try { stdp.println(f\"{1 / c}\"); }\n"
        "    catch (exc.DivisionPorCero e) { stdp.println(\"atrapada\"); };\n"
        "    return 0;\n"
        "}\n")}, main="excepciones.srcx", args=["--run", "interpreter"])
    assert code == 0, (code, out, err)
    assert "atrapada" in out, out
    assert "SEM010" not in out + err, (out, err)


def test_a_program_that_only_finds_itself_is_told_why():
    code, out, err = run_project({"utilidad.srcx": (
        "#import utilidad\n"
        "fn main() -> int { return 0; }\n")}, main="utilidad.srcx")
    assert code != 0, (code, out, err)
    salida = out + err
    assert "SEM009" in salida and "SEM010" not in salida, salida
    assert "se omitió 'utilidad.srcx'" in salida and "a sí mismo" in salida, salida
