"""e2e: lo que compilaba y fallaba AL EJECUTAR ahora no compila (código de
salida 1, el diagnóstico con su código y ninguna ejecución), y un AVISO
dentro de una librería ya no impide ejecutar el programa.

Cada caso dice qué error de ejecución daba antes: es lo que cambia para
quien lo usa. Los diagnósticos en sí (posición, que no salga nada más) los
fija ``negative_tests/test_diagnostics_read_only_and_dubious.py``.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import run_project, run_source  # noqa: E402


def _rejected(source: str, code: str, old_runtime_code: str) -> None:
    exit_code, out, err = run_source(source, args=["--run", "interpreter"])
    text = out + err
    assert exit_code == 1, (exit_code, text)
    assert f"{code}:" in text, text
    assert old_runtime_code not in text, text
    assert "error de runtime" not in text, text


def test_a_global_used_before_its_declaration_does_not_compile():
    """Antes: RT006 ('b' no está ligado en runtime)."""
    _rejected("var int a = b + 1;\n"
              "var int b = 2;\n"
              "fn main() -> int { return a; }\n", "SEM045", "RT006")


def test_writing_a_char_of_a_str_does_not_compile():
    """Antes: RT014 ('hola' no es indexable)."""
    _rejected("fn main() -> int {\n"
              "    var str s = \"hola\";\n"
              "    s[0] = 'x';\n"
              "    return 0;\n}\n", "SEM031", "RT014")


def test_borrowing_a_scalar_of_a_vector_does_not_compile():
    """Antes: RT011 ('&' sobre un elemento que no es un objeto)."""
    _rejected("#import array.vector as vec\n"
              "fn main() -> int {\n"
              "    var vec.Vector<int> v = vec.dynamic<int>(2);\n"
              "    v.push(1);\n"
              "    var int ptr p = v.at(0);\n"
              "    return 0;\n}\n", "SEM013", "RT011")


def test_len_of_a_primitive_does_not_compile():
    """Antes: RT006 ('len' no está ligado en runtime). ``print(5)`` ya no
    está aquí: escribe el entero como un f-string (decisión del mantenedor,
    ver ``test_print_of_primitives.py``)."""
    _rejected("fn main() -> int {\n"
              "    var int n = len(5);\n"
              "    return n;\n}\n", "SEM001", "RT006")


def test_hash_of_a_function_in_a_generic_does_not_compile():
    """Antes: RT011 al ejecutar el hash dentro del genérico."""
    _rejected("fn g(int x) -> int { return x; }\n"
              "fn h<T>(T x) -> int { return hash(x); }\n"
              "fn main() -> int { return h<fn(int) -> int>(g); }\n",
              "AST006", "RT011")


def test_unreachable_code_warns_and_the_program_runs():
    """SEM048 es un AVISO: el programa se ejecuta y hace lo que dice."""
    exit_code, out, err = run_source(
        "#import io.stdp as stdp\n"
        "fn f() -> int {\n"
        "    return 7;\n"
        "    stdp.println(\"nunca\");\n"
        "}\n"
        "fn main() -> int { stdp.println(f\"{f()}\"); return 0; }\n",
        args=["--run", "interpreter"])
    assert exit_code == 0, (exit_code, out, err)
    assert "SEM048" in out + err, out + err
    assert out.strip().splitlines()[-1] == "7", out


def test_a_warning_inside_a_library_does_not_stop_the_program():
    """Antes, CUALQUIER diagnóstico de una unidad de librería —también un
    aviso como SEM030— dejaba sin emitir su .phir y el programa no se
    ejecutaba ('la unidad tiene errores'). Ahora el aviso se dice (con el
    título 'avisos') y la unidad se emite."""
    exit_code, out, err = run_project({
        "col.libsrx": ("enum Color { ROJO, VERDE };\n"
                       "fn f(Color c) -> int {\n"
                       "    match (c) { case Color.ROJO: { return 1; } }\n"
                       "    return 0;\n"
                       "}\n"
                       "#export as col\n"),
        "main.srcx": ("#import col\n"
                      "#import io.stdp as stdp\n"
                      "fn main() -> int {\n"
                      "    stdp.println(f\"{col.f(col.Color.ROJO)}\");\n"
                      "    return 0;\n"
                      "}\n"),
    }, args=["--run", "interpreter"])
    text = out + err
    assert exit_code == 0, (exit_code, text)
    assert "SEM030" in text and "avisos de la unidad 'col'" in text, text
    assert "su .phir no se emitió" not in text, text
    assert out.strip().splitlines()[-1] == "1", out
