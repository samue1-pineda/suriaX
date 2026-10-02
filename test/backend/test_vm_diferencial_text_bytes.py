"""backend/vm_diferencial: enums que poseen, byte, archivos binarios, text y formatos.

Parte de ``test_vm_diferencial.py`` (partido por tema); lo compartido esta en
``vm_diferencial_support.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import omitir  # noqa: E402
from vm_diferencial_support import (  # noqa: E402
    _comparar,
    _en_linea,
    _hay_cxx,
)

# --------------------------------------------------------------------------- #
# lote 10: enums que poseen, literales, byte, archivos binarios, text, formatos
# --------------------------------------------------------------------------- #

def test_una_variante_con_destructor_y_los_temporales_por_tipo():
    """Un payload con destructor se destruye con su variante (era SEM029), y
    un temporal que posee solo por sus campos o su payload (o un 'T'
    descartado dentro de un generico) muere al cerrar la sentencia."""
    _comparar(_en_linea("""\
#from io #import stdp
#import array.vector as vec
struct { int id; } R;
hook fn __free__(R ptr r) -> void { stdp.println(f"libera {r.id}"); }
struct { R r; } Caja;
enum E { V(R), Par(R, int), Fin };
fn hace() -> Caja { return Caja{ r: R{ id: 2 } }; }
fn toma<T>(T x) -> int { return 0; }
fn descarta<T>(vec.Vector<T> ptr mutable v) -> void { v.pop(); }
fn main() -> int {
    Caja{ r: R{ id: 1 } };
    hace();
    var E a = E.V(R{ id: 3 });
    var E b = E.Fin;
    a = E.Par(R{ id: 4 }, 7);
    E.V(R{ id: 5 });
    match (a) { case E.Par(r, n) { stdp.println(f"par {r.id} {n}"); }; case E.V(r) { }; case E.Fin { }; };
    var vec.Vector<E> ve = vec.dynamic<E>(1);
    ve.push(E.V(R{ id: 6 }));
    ve.push(E.Fin);
    ve.push(E.V(R{ id: 8 }));
    var vec.Vector<R> vr = vec.dynamic<R>(1);
    vr.push(R{ id: 9 });
    vr.push(R{ id: 10 });
    descarta<R>(&vr);
    toma<E>(E.V(R{ id: 11 }));
    stdp.println("fin");
    return 0;
}
"""))


def test_byte_en_los_dos_motores():
    """'byte': literales que caben, 'cast' que trunca, '~' de 8 bits, bloques
    compactos en la VM y 'hash' como el de un 'int'."""
    _comparar(_en_linea("""\
#from io #import stdp
#import mem
fn primero() -> byte { return 0x41; }
fn main() -> int {
    var byte a = 200;
    var byte b = 0x0F;
    var byte c = a & b;
    var byte d = ~b;
    var int n = cast<int>(a) + 100;
    var byte t = cast<byte>(n);
    var bool m = a > b and c == 8 and d == 0xF0;
    var byte ptr mutable blq = mem.reserve<byte>(4);
    blq[0] = 7;
    blq[1] = a | 1;
    stdp.println(f"{a} {b} {c} {d} {n} {t} {m} {blq[0]} {blq[1]} {primero()} {hash(a) == hash(200)}");
    mem.release<byte>(blq);
    return 0;
}
"""))


def test_archivos_binarios_en_los_dos_motores():
    """'read_bytes'/'write_bytes': 301 bytes de ida y vuelta, un archivo
    vacio y el ErrorDeArchivo de uno que no existe."""
    _comparar(_en_linea("""\
#from io #import stdp
#import array.vector as vec
#import sistema.archivos as fs
#import excepciones as exc
fn main() -> int {
    var vec.Vector<byte> v = vec.dynamic<byte>(2);
    var int i = 0;
    while (i < 300) { v.push(cast<byte>(i * 7)); i = i + 1; };
    v.push(0xFF);
    fs.write_bytes("datos.bin", &v);
    var vec.Vector<byte> w = fs.read_bytes("datos.bin");
    var int suma = 0;
    var bool igual = w.len() == v.len();
    i = 0;
    while (i < w.len()) {
        suma = suma + cast<int>(w.get(i));
        if (w.get(i) != v.get(i)) { igual = false; };
        i = i + 1;
    };
    stdp.println(f"{w.len()} {suma} {igual} {w.get(1)} {w[300]}");
    var vec.Vector<byte> vacio = vec.dynamic<byte>(1);
    fs.write_bytes("vacio.bin", &vacio);
    stdp.println(f"vacio {fs.read_bytes("vacio.bin").len()}");
    try { fs.read_bytes("no_existe.bin"); } catch (exc.ErrorDeArchivo e) { stdp.println(e.mensaje); };
    return 0;
}
"""))


def test_la_libreria_text_en_los_dos_motores():
    """'text': indices en CARACTERES (con 'ñ' y 'ú'), 'join', 'parse_int' con
    sus limites y UTF-8 de ida y vuelta; los errores con el mismo mensaje."""
    _comparar(_en_linea("""\
#from io #import stdp
#import array.vector as vec
#import text
#import excepciones as exc
fn main() -> int {
    var str s = "año nuevo, código ñandú";
    stdp.println(text.slice(s, 4, 9));
    stdp.println(f"{text.find(s, "código")} {text.find(s, "zzz")} {text.find_from(s, "n", 5)}");
    stdp.println(f"{text.starts_with(s, "año")} {text.ends_with(s, "dú")} {text.ends_with(s, "x")}");
    var vec.Vector<str> partes = vec.dynamic<str>(1);
    var int i = 0;
    while (i < 5) { partes.push(f"p{i}"); i = i + 1; };
    stdp.println(text.join(&partes, ", "));
    stdp.println(f"{text.parse_int("-42") + 1} {text.parse_int("+7")} {text.parse_int("9223372036854775807")} {text.parse_int("-9223372036854775808")}");
    try { text.parse_int("12a"); } catch (exc.ConversionInvalida e) { stdp.println(e.mensaje); };
    try { text.parse_int("9223372036854775808"); } catch (exc.ConversionInvalida e) { stdp.println(e.mensaje); };
    try { text.slice(s, 3, 99); } catch (exc.IndiceFueraDeRango e) { stdp.println(e.mensaje); };
    var vec.Vector<byte> b = text.to_bytes("ñu€");
    stdp.println(f"{b.len()} {b.get(0)} {b.get(1)} {text.from_bytes(&b)}");
    b.set(0, 0xFF);
    try { text.from_bytes(&b); } catch (exc.ConversionInvalida e) { stdp.println(e.mensaje); };
    stdp.println(f"[{text.slice(s, 0, 0)}] {len(text.join(&partes, ""))}");
    return 0;
}
"""))


def test_formatos_de_fstring_en_los_dos_motores():
    """'!r' (comillas y escapes, enums calificados, structs anidados), las
    bases, el relleno con ceros y con espacios y la precision de un float."""
    _comparar(_en_linea("""\
#from io #import stdp
enum Color { Rojo, Verde };
enum Figura { Circulo(float), Nombre(str), Nada };
struct { int x; int y; str nombre; } Punto;
struct { T v; Color c; } Caja<T>;
struct { Punto a; char k; float? f; } Par;
fn main() -> int {
    var str s = "ho\\"la\\n";
    var char c = '\\'';
    var int n = 255;
    var int neg = -5;
    var byte b = 10;
    var float f = 3.14159;
    var Punto p = Punto{ y: 2, x: 1, nombre: "a" };
    stdp.println(f"{s!r} {c!r} {s} [{c}]");
    stdp.println(f"{n:x} {n:X} {n:b} {n:o} {n:08b} {neg:x} {neg:05d} {n:6} {b:08b} {b:02X}");
    stdp.println(f"{f:.2f} {f:8.3f} {f:08.1f} {-f:.0f} {f:f}");
    stdp.println(f"[{s:10}] [{c:3}] [{Color.Verde:6}] [{Color.Verde!r}]");
    stdp.println(f"{p} {p!r}");
    var Figura g = Figura.Nombre("z");
    stdp.println(f"{g} {g!r} {Figura.Circulo(2.5)!r} {Figura.Nada!r}");
    var Caja<Color> k = Caja<Color>{ v: Color.Rojo, c: Color.Verde };
    var Par pa = Par{ a: p, k: 'q', f: null };
    stdp.println(f"{k} {pa!r:40}|");
    return 0;
}
"""))


def test_extern_cpp_con_byte():
    """Un 'byte' cruza como 'uint8_t' y un 'byte ptr' como el buffer: en la
    VM es su memoria compacta, sin copiarla."""
    if not _hay_cxx():
        omitir("no hay compilador de C++ (g++/clang++)")
    _comparar(_en_linea("""\
#extern cpp{
#include <cstdint>
extern "C" std::uint8_t invierte(std::uint8_t b) { return static_cast<std::uint8_t>(255 - b); }
extern "C" void suma_uno(std::uint8_t* xs, long long n) { for (long long i = 0; i < n; ++i) xs[i] += 1; }
}
#import mem
fn __write__(str s) -> void;
fn invierte(byte b) -> byte;
fn suma_uno(byte ptr mutable xs, int n) -> void;
fn main() -> int {
    var byte ptr mutable xs = mem.reserve<byte>(3);
    xs[0] = 0; xs[1] = 254; xs[2] = 255;
    suma_uno(xs, 3);
    __write__(f"{invierte(10)} {xs[0]} {xs[1]} {xs[2]}\\n");
    mem.release<byte>(xs);
    return 0;
}
"""))


def test_parse_float_y_los_bits_de_un_float_en_los_dos_motores():
    """'text.parse_float' con redondeo CORRECTO (los empates que van al par,
    el subnormal mas chico, 2^53+1) y 'mem.float_bits' / 'float_from_bits':
    los MISMOS 64 bits en el interprete ('float()' de Python) y en la VM
    ('strtod'). Es lo que necesita el compilador escrito en suriaX para
    escribir un literal 'float' en el '.phir'."""
    _comparar(_en_linea("""\
#from io #import stdp
#import array.vector as vec
#import text
#import mem
#import excepciones as exc
fn main() -> int {
    var vec.Vector<str> casos = vec.dynamic<str>(1);
    casos.push("0.1"); casos.push("3.25"); casos.push("-0.0"); casos.push("1e23");
    casos.push("9007199254740993"); casos.push("2.2250738585072011e-308");
    casos.push("1.7976931348623157e308"); casos.push("5e-324");
    casos.push("2.4703282292062328e-324"); casos.push("2.4703282292062327e-324");
    casos.push("1e-400"); casos.push("+7.5E+2"); casos.push("123456789012345678901234567890");
    casos.push("0.30000000000000004"); casos.push("1.00000000000000011102230246251565404236316680908203125");
    var int i = 0;
    while (i < casos.len()) {
        var float x = text.parse_float(casos.get(i));
        var int b = mem.float_bits(x);
        stdp.println(f"{casos.get(i)} -> {b:016X} {x} {mem.float_from_bits(b) == x}");
        i = i + 1;
    };
    stdp.println(f"{mem.float_bits(1.0):X} {mem.float_from_bits(0x4004000000000000)}");
    var vec.Vector<str> malos = vec.dynamic<str>(1);
    malos.push("1e400"); malos.push("1."); malos.push(".5"); malos.push("1e"); malos.push("inf"); malos.push(" 1"); malos.push("");
    i = 0;
    while (i < malos.len()) {
        try { text.parse_float(malos.get(i)); } catch (exc.ConversionInvalida e) { stdp.println(e.mensaje); };
        i = i + 1;
    };
    return 0;
}
"""))
