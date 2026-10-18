"""negative_tests/diagnostics: ``sizeof`` sin ``__sizeof__`` no compila.

Decisión del mantenedor: el tamaño de un tipo lo da SIEMPRE su hook
``__sizeof__``, y un ``sizeof`` que no puede responder (un primitivo, un
tipo propio sin el hook, una función) fallaba siempre al ejecutar con
``RT011``. Ahora es ``SEM001`` al compilar. Dentro de un genérico,
``sizeof`` de su ``T`` lo decide cada instancia, en la llamada, como
``hash`` y las copias.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import analyze  # noqa: E402


def _diagnostics(source: str) -> list:
    """``[(código, línea, columna)]`` de ``source``, en orden."""
    _, _, errors = analyze(source)
    return [(e.code, e.line, e.column) for e in errors]


def _expect(source: str, expected: list) -> None:
    got = _diagnostics(source)
    assert got == expected, f"se esperaba {expected}; se obtuvo {got}"


B = "struct { int n; } B;\n"
B_SIZED = B + "hook fn __sizeof__(B ptr b) -> int { return 8; }\n"
SIZE_OF = "fn size_of<T>(T x) -> int { return sizeof(x); }\n"


def _main(body: str, before: str = "") -> str:
    return before + "fn main() -> int {\n" + body + "\n    return 0;\n}\n"


def test_sizeof_of_a_primitive_does_not_compile():
    _expect(_main("    var int n = sizeof(int);"), [("SEM001", 2, 17)])


def test_sizeof_of_a_primitive_value_does_not_compile():
    _expect(_main("    var int a = 3;\n    var int n = sizeof(a);"),
            [("SEM001", 3, 17)])


def test_sizeof_of_a_type_without_the_hook_does_not_compile():
    _expect(_main("    var int n = sizeof(B);", B), [("SEM001", 3, 17)])


def test_sizeof_of_a_function_does_not_compile():
    _expect(_main("    var fn(int) -> int g = twice;\n"
                  "    var int n = sizeof(g);",
                  "fn twice(int x) -> int { return x * 2; }\n"),
            [("SEM001", 4, 17)])


def test_sizeof_with_the_hook_compiles():
    _expect(_main("    var int n = sizeof(B);\n"
                  "    var B b = B{n: 1};\n"
                  "    var int m = sizeof(b);", B_SIZED), [])


def test_a_generic_sizeof_is_decided_by_each_instance():
    # el cuerpo generico compila; la instancia con 'int' no, en la llamada
    _expect(_main("    var int n = size_of(5);", SIZE_OF), [("SEM001", 3, 17)])


def test_a_generic_sizeof_with_a_sized_type_compiles():
    _expect(_main("    var B b = B{n: 1};\n    var int n = size_of(b);",
                  B_SIZED + SIZE_OF), [])


def test_a_generic_sizeof_reaches_the_outer_instance():
    # 'outer' no mide nada por si mismo: lo pide 'size_of' con SU T, asi que
    # decide la instancia de 'outer'
    outer = "fn outer<U>(U y) -> int { return size_of(y); }\n"
    _expect(_main("    var int n = outer(5);", SIZE_OF + outer),
            [("SEM001", 4, 17)])
    _expect(_main("    var B b = B{n: 1};\n    var int n = outer(b);",
                  B_SIZED + SIZE_OF + outer), [])
