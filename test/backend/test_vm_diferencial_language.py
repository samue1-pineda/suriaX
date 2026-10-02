"""backend/vm_diferencial: orden y texto, sizeof, globales, #extern cpp y operadores de bits.

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

def test_resto_de_flotantes_orden_de_cadenas_y_enums_en_texto():
    """'%' entre flotantes es 'fmod' (NaN con divisor cero), '<' entre
    cadenas ordena por punto de codigo, y un enum en un f-string se escribe
    como en el interprete: su numero si no lleva payload, 'Nodo(3, x)' si
    lleva."""
    _comparar(_en_linea("""\
#from io #import stdp
enum Color { Rojo, Verde };
enum Arbol { Hoja, Nodo(int, str), Par(float, bool) };
fn main() -> int {
    var float z = 0.0;
    stdp.println(f"{7.5 % 2.0} {-7.5 % 2.0} {7.5 % -2.0} {5.0 % z}");
    var str a = "abc";
    var str b = "abd";
    var str ene = "ñ";
    var str zeta = "z";
    stdp.println(f"{a < b} {b <= a} {ene > zeta} {a >= a}");
    var Color c = Color.Verde;
    var Arbol n = Arbol.Nodo(3, zeta);
    stdp.println(f"{c} {n} {Arbol.Par(0.1, true)} {Arbol.Hoja}");
    return 0;
}
"""))


def test_sizeof_sin_hook_es_rt011_en_los_dos_motores():
    """Sin '__sizeof__' no hay tamaño que dar: el interprete falla con RT011
    al ejecutarlo, y la VM ahora igual (antes no compilaba)."""
    _comparar(_en_linea("""\
#from io #import stdp
struct { int x; } P;
fn main() -> int {
    stdp.println("antes");
    stdp.println(f"{sizeof(P)}");
    return 0;
}
"""))


def test_una_global_propia_y_un_null_copiado():
    """Una global que es dueña de un objeto se libera cuando 'main' vuelve
    (sin su '__free__': el interprete tampoco lo corre), y copiar un 'P?'
    que vale null da null (antes la VM abortaba)."""
    _comparar(_en_linea("""\
#from io #import stdp
struct { int x; } P;
struct { int y; } Q;
hook fn __free__(P ptr p) -> void { stdp.println(f"libera {p.x}"); }
var P global = P{ x: 1 };
var Q otra = Q{ y: 3 };
fn main() -> int {
    var Q? a = null;
    var Q? b = a;
    var Q? c = Q{ y: 2 };
    b = c;
    stdp.println(f"{global.x} {otra.y} {a == null} {b == null}");
    return 0;
}
"""))


def test_extern_cpp_se_liga_igual_en_los_dos_motores():
    """'#extern cpp' en la VM: el C++ del programa se construye junto al
    .phir y cumple sus prototipos, con la misma tabla de tipos que el
    interprete (int64, double, bool, un code point, 'const char*') y hasta 6
    parametros mezclados. Un bloque de 'float' cruza como su memoria: C++
    escribe en las celdas de la VM y suriaX lo ve al volver."""
    if not _hay_cxx():
        omitir("no hay compilador de C++ (g++/clang++)")
    _comparar(_en_linea("""\
#extern cpp{
#include <cstdio>
#include <cstdint>
extern "C" void escribe(const char* texto) { std::printf("[cpp] %s\\n", texto); std::fflush(stdout); }
extern "C" long long duplica(long long n) { return n * 2; }
extern "C" double mitad(double x) { return x / 2.0; }
extern "C" bool par(long long n) { return n % 2 == 0; }
extern "C" std::uint32_t siguiente(std::uint32_t c) { return c + 1; }
extern "C" double mezcla(long long a, double b, long long c, double d, bool e, double f) {
    return a + b + c + d + (e ? 100 : 0) + f;
}
extern "C" void pinta(double* xs, long long n) { for (long long i = 0; i < n; ++i) xs[i] *= 10.0; }
}
#import mem
fn __write__(str s) -> void;
fn escribe(str texto) -> void;
fn duplica(int n) -> int;
fn mitad(float x) -> float;
fn par(int n) -> bool;
fn siguiente(char c) -> char;
fn mezcla(int a, float b, int c, float d, bool e, float f) -> float;
fn pinta(float ptr mutable xs, int n) -> void;
fn main() -> int {
    escribe("hola");
    __write__(f"{duplica(21)} {mitad(5.0)} {par(4)} {par(7)} {siguiente('a')}\\n");
    __write__(f"{mezcla(1, 0.5, 2, 0.25, true, 0.125)}\\n");
    var float ptr mutable xs = mem.reserve<float>(3);
    xs[0] = 1.5; xs[1] = 2.0; xs[2] = -0.5;
    pinta(xs, 3);
    __write__(f"{xs[0]} {xs[1]} {xs[2]}\\n");
    mem.release<float>(xs);
    return 0;
}
"""))


def test_extern_cpp_lo_que_no_cruza_falla_igual():
    """Lo que no cruza la frontera: un bloque de 'str' al llamar (RT018) y un
    prototipo que ningun C++ cumple (RT008), con el mismo codigo en los dos
    motores."""
    if not _hay_cxx():
        omitir("no hay compilador de C++ (g++/clang++)")
    _comparar(_en_linea("""\
#import mem
#extern cpp{
extern "C" void toca(void* p) { (void)p; }
}
fn toca(str ptr mutable p) -> void;
fn main() -> int {
    var str ptr mutable s = mem.reserve<str>(2);
    s[0] = "a"; s[1] = "b";
    toca(s);
    return 0;
}
"""))
    _comparar(_en_linea("""\
#extern cpp{
extern "C" int otra() { return 1; }
}
fn falta(int x) -> int;
fn main() -> int {
    return falta(1);
}
"""))


def test_operadores_de_bits():
    """'&', '|', '^', '~', '<<', '>>' y sus compuestas sobre 'int' de 64 bits:
    '<<' envuelve, '>>' conserva el signo y un desplazamiento fuera de
    [0, 64) es 'excepciones.DesplazamientoInvalido' (EXC005)."""
    _comparar(_en_linea("""\
#from io #import stdp
#import excepciones as exc
fn mezcla(int h, int x) -> int { return (h ^ x) * 1099511628211; }
fn main() -> int {
    var int a = 12;
    var int b = 10;
    stdp.println(f"{a & b} {a | b} {a ^ b} {~a} {a << 2} {a >> 1} {-16 >> 2} {1 << 63}");
    stdp.println(f"{a & b == 8} {1 + 2 << 1} {a | b ^ 3 & 1} {mezcla(-3750763034362895579, 97)}");
    var int x = 5;
    x <<= 3; x >>= 1; x &= 12; x |= 3; x ^= 1;
    stdp.println(f"{x}");
    var int n = 64;
    try { stdp.println(f"{1 << n}"); } catch (exc.DesplazamientoInvalido e) { stdp.println(e.mensaje); };
    n = -1;
    stdp.println(f"{1 >> n}");
    return 0;
}
"""))


_COSA = """\
public struct { int x; } Plano;
public enum Forma { Circulo(int), Nada };
public fn doble(int x) -> int { return x * 2; }
public fn id<T>(T x) -> T { return x; }
#export as cosa
"""


def test_lo_traido_con_from_se_usa_igual_en_los_dos_motores():
    """Regresión: la VM ligaba todo '#from' como un SUBMÓDULO, y la llamada a
    una función traída así ('#from cosa #import doble; doble(3)') quedaba
    SIN RESOLVER mientras el intérprete la ejecutaba. Con alias, genérica, y
    un struct y un enum traídos como TIPOS."""
    def preparar(tmp: str) -> str:
        # la librería junto al fuente: es la primera ruta de búsqueda
        with open(os.path.join(tmp, "cosa.libsrx"), "w", encoding="utf-8") as fh:
            fh.write(_COSA)
        return _en_linea("""\
#from io #import stdp
#from cosa #import doble
#from cosa #import doble as d
#from cosa #import id
#from cosa #import Plano as P
#from cosa #import Forma
fn main() -> int {
    var str x = id("x");
    var P p = P{ x: 7 };
    var Forma f = Forma.Circulo(d(p.x));
    match (f) {
        case Forma.Circulo(r): { stdp.println(f"{doble(3)} {d(4)} {id<int>(5)} {x} {r}"); }
        case Forma.Nada: { stdp.println("nada"); }
    }
    return doble(1);
}
""")(tmp)
    _comparar(preparar)


def test_un_dunder_fn_se_llama_como_metodo_en_los_dos_motores():
    """Regresión: la VM indexaba los métodos por el nombre SIN guiones
    ('Punto.doble') y la llamada los busca como se escriben
    ('p.__doble__()'): un 'dunder fn' quedaba SIN RESOLVER mientras el
    intérprete lo ejecutaba. Junto a métodos de '@impl', que no cambian."""
    _comparar(_en_linea("""\
#from io #import stdp
struct { int x; int y; } Punto;
@impl Punto {
    fn suma(Punto ptr self) -> int { return self.x + self.y; }
}
dunder fn __doble__(Punto ptr self) -> int { return self.suma() * 2; }
fn main() -> int {
    var Punto p = Punto{ x: 1, y: 2 };
    stdp.println(f"{p.suma()} {p.__doble__()}");
    return p.__doble__();
}
"""))
