"""e2e/lote10 — literales con base, 'byte', archivos binarios, 'text' y
el formato de un f-string, con la salida que se espera (el diferencial de
'test/backend' compara los dos motores; aqui se fija QUE deben dar).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import assert_output, run_program  # noqa: E402

W = "#from io #import stdp\n"


def _run(cuerpo: str, esperado: str, extra: str = "") -> None:
    assert_output(W + extra + "fn main() -> int {\n" + cuerpo + "\n    return 0;\n}\n",
                  esperado)


def test_literales_con_base_y_separadores():
    """Son otra forma de escribir un 'int'. Con base, un PATRON DE BITS: el
    bit 63 encendido da un negativo."""
    _run('    stdp.println(f"{0xFF} {0b1010} {0o755} {1_000_000} {0xFFFF_FFFF_FFFF_FFFF} {3.25_5}");',
         "255 10 493 1000000 -1 3.255\n")


def test_byte_se_compara_y_se_enmascara():
    _run('    var byte a = 0xF0;\n    var byte b = 0x0F;\n'
         '    stdp.println(f"{a | b} {a & b} {~a} {cast<byte>(300)} {cast<int>(a) + 1} {a > b}");',
         "255 0 15 44 241 true\n")


def test_archivos_binarios():
    _run('    var vec.Vector<byte> v = vec.dynamic<byte>(1);\n'
         '    v.push(0); v.push(200); v.push(0xFF);\n'
         '    fs.write_bytes("b.bin", &v);\n'
         '    var vec.Vector<byte> w = fs.read_bytes("b.bin");\n'
         '    stdp.println(f"{w.len()} {w.get(0)} {w.get(1)} {w.get(2)}");',
         "3 0 200 255\n",
         extra="#import array.vector as vec\n#import sistema.archivos as fs\n")


def test_la_libreria_text():
    _run('    var vec.Vector<str> p = vec.dynamic<str>(1);\n'
         '    p.push("a"); p.push("b"); p.push("c");\n'
         '    stdp.println(f"{text.slice("mañana", 1, 4)} {text.find("mañana", "na")} '
         '{text.join(&p, "-")} {text.parse_int("-12") * 2} {text.to_bytes("ñ").len()}");',
         "aña 4 a-b-c -24 2\n",
         extra="#import array.vector as vec\n#import text\n")


def test_parse_int_invalido_es_conversion_invalida():
    _run('    try { text.parse_int("1x"); } catch (exc.ConversionInvalida e) { stdp.println(e.mensaje); };',
         "'1x' no es un entero\n",
         extra="#import text\n#import excepciones as exc\n")


def test_formatos_de_un_fstring():
    _run('    var int n = 255;\n    var float f = 2.5;\n    var str s = "a\\"b";\n'
         '    stdp.println(f"{n:x} {n:08b} {-n:05d} {f:.3f} [{n:5}] [{s:4}] {s!r} {\'q\'!r}");',
         "ff 11111111 -0255 2.500 [  255] [a\"b ] \"a\\\"b\" 'q'\n")


def test_repr_de_structs_y_enums():
    _run('    var P p = P{ y: 2, x: 1 };\n'
         '    stdp.println(f"{p} {C.Verde} {C.Verde!r}");',
         "P{x: 1, y: 2} Verde C.Verde\n",
         extra="struct { int x; int y; } P;\nenum C { Rojo, Verde };\n")


def test_parse_float_y_bits_de_un_float():
    """El 'double' mas cercano (como Python) y sus 64 bits IEEE-754."""
    _run('    stdp.println(f"{mem.float_bits(text.parse_float("0.1")):X} '
         '{mem.float_bits(1.0):X} {mem.float_from_bits(0x4004000000000000)} '
         '{text.parse_float("-2.5e-3")}");',
         "3FB999999999999A 3FF0000000000000 2.5 -0.0025\n",
         extra="#import text\n#import mem\n")


def test_parse_float_invalido_es_conversion_invalida():
    _run('    try { text.parse_float("1e400"); } catch (exc.ConversionInvalida e) '
         '{ stdp.println(e.mensaje); };\n'
         '    try { text.parse_float(".5"); } catch (exc.ConversionInvalida e) '
         '{ stdp.println(e.mensaje); };',
         "'1e400' no cabe en un float\n'.5' no es un float\n",
         extra="#import text\n#import excepciones as exc\n")
