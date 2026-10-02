"""backend/vm_diferencial: with, temporales y direcciones de campos.

Parte de ``test_vm_diferencial.py`` (partido por tema); lo compartido esta en
``vm_diferencial_support.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vm_diferencial_support import (  # noqa: E402
    _comparar,
    _en_linea,
)

def test_with_recurso_guardian_y_receptor():
    """'with': recursos con nombre (su __free__ al salir, en orden inverso),
    la forma de llamada ('with f(var T x, ...)'), un guardian sin nombre que
    deshace un cambio al salir y un receptor ('.campo') que modifica el lugar
    mismo, no una copia."""
    _comparar(_en_linea("""\
#from io #import stdp
struct { str nombre; } Recurso;
hook fn __free__(Recurso ptr r) -> void { stdp.println(f"cierra {r.nombre}"); }
fn abre(str n) -> Recurso { stdp.println(f"abre {n}"); return Recurso{ nombre: n }; }
fn abre_en(str n, str modo) -> Recurso { return Recurso{ nombre: n + ":" + modo }; }

var str idioma = "es";
struct { str anterior; } Idioma;
hook fn __free__(Idioma ptr g) -> void { idioma = g.anterior; }
fn cambiar_idioma(str nuevo) -> Idioma {
    var Idioma g = Idioma{ anterior: idioma };
    idioma = nuevo;
    return g;
}

struct { int ancho; int alto; str titulo; } Ventana;
@impl Ventana {
    fn show(Ventana ptr self) -> void { stdp.println(f"{self.titulo} {self.ancho}x{self.alto}"); }
}

fn main() -> int {
    with (var Recurso a = abre("a"), var Recurso b = abre("b")) {
        stdp.println(f"usa {a.nombre} y {b.nombre}");
    };
    with abre_en(var Recurso f, "x.txt", "w") {
        stdp.println(f"usa {f.nombre}");
    };
    stdp.println(f"idioma {idioma}");
    with (cambiar_idioma("en")) {
        stdp.println(f"idioma {idioma}");
    };
    stdp.println(f"idioma {idioma}");
    var Ventana v = Ventana{ ancho: 0, alto: 0, titulo: "sin" };
    with (v) {
        .ancho = 900;
        .alto = 600;
        .titulo = "hola";
        .show();
    };
    stdp.println(f"{v.ancho} {v.titulo}");
    with (abre("temporal")) {
        stdp.println(f"receptor {.nombre}");
    };
    return 0;
}
"""))


def test_un_temporal_se_libera_aunque_otra_parte_de_la_expresion_lance():
    """'usa(C{...}, falla())' y 'Par{ a: C{...}, b: falla() }': lo ya hecho
    se libera por el camino de la excepcion (antes la VM lo perdia), tambien
    dentro de un bucle. El diferencial exige cero objetos vivos."""
    _comparar(_en_linea("""\
#from io #import stdp
#import excepciones as exc
struct { int v; } C;
struct { C a; C b; } Par;
fn falla() -> C { throw exc.ValorInvalido{ mensaje: "no" }; }
fn usa(C x, C y) -> int { return x.v + y.v; }
fn main() -> int {
    try { stdp.println(f"{usa(C{ v: 1 }, falla())}"); } catch (exc.ValorInvalido e) { stdp.println("1"); };
    try { var Par p = Par{ a: C{ v: 1 }, b: falla() }; } catch (exc.ValorInvalido e) { stdp.println("2"); };
    var int i = 0;
    while (i < 3) {
        try { usa(C{ v: i }, falla()); } catch (exc.ValorInvalido e) { i = i + 1; };
    };
    stdp.println(f"{i}");
    return 0;
}
"""))


def test_with_open_de_sistema_archivos():
    """'with open(var File f, ruta, modo)': "w" escribe al cerrar, "a"
    agrega, "r" lee; un archivo que no existe es ErrorDeArchivo y un modo
    desconocido o un uso equivocado, ValorInvalido. Un 'File' a medio hacer
    cuando 'open' lanza no queda vivo."""
    _comparar(_en_linea("""\
#from io #import stdp
#import sistema.archivos as arch
#import excepciones as exc
fn main() -> int {
    with arch.open(var arch.File f, "salida.txt", "w") {
        f.write("hola\\n");
        f.write("mundo\\n");
    };
    with arch.open(var arch.File g, "salida.txt", "a") {
        g.write("mas\\n");
    };
    with arch.open(var arch.File r, "salida.txt", "r") {
        stdp.println(r.read());
    };
    try {
        with arch.open(var arch.File x, "no_existe.txt", "r") { stdp.println("no"); };
    } catch (exc.ErrorDeArchivo e) { stdp.println("no existe"); };
    try {
        with arch.open(var arch.File x, "salida.txt", "q") { };
    } catch (exc.ValorInvalido e) { stdp.println(e.mensaje); };
    with arch.open(var arch.File w, "salida.txt", "r") {
        try { w.write("x"); } catch (exc.ValorInvalido e) { stdp.println(e.mensaje); };
    };
    return 0;
}
"""))


def test_la_direccion_de_un_campo_escalar():
    """'&p.x' con 'x' escalar: el campo guarda una celda en todas las
    instancias de su struct (se decide para todo el programa), que se copia
    y se libera con el struct. Tambien por un puntero y en un campo anidado."""
    _comparar(_en_linea("""\
#from io #import stdp
struct { int x; float y; str n; } P;
struct { P a; int k; } Q;
fn inc(int ptr mutable p) -> void { p[0] = p[0] + 1; }
fn mitad(float ptr mutable f) -> void { f[0] = f[0] / 2.0; }
fn main() -> int {
    var P p = P{ x: 1, y: 3.0, n: "p" };
    inc(&p.x);
    inc(&p.x);
    mitad(&p.y);
    var P c = p;
    inc(&c.x);
    p.x = p.x + 10;
    p.x++;
    var Q q = Q{ a: P{ x: 5, y: 1.0, n: "q" }, k: 0 };
    inc(&q.a.x);
    inc(&q.k);
    var P ptr mutable pp = &p;
    inc(&pp.x);
    stdp.println(f"{p.x} {p.y} {c.x} {q.a.x} {q.k}");
    return 0;
}
"""))


def test_los_temporales_de_una_condicion_mueren_al_evaluarla():
    """Un temporal con destructor en la condicion de un 'while' o un 'if'
    muere al terminar de evaluarla (como en C++), en cada vuelta: antes el
    interprete los acumulaba hasta salir del bucle y la VM perdia todos menos el ultimo."""
    _comparar(_en_linea("""\
#from io #import stdp
struct { int v; } R;
hook fn __free__(R ptr r) -> void { stdp.println(f"libera {r.v}"); }
fn crea(int v) -> R { return R{ v: v }; }
fn main() -> int {
    var int i = 0;
    while (crea(i).v < 3) {
        stdp.println(f"vuelta {i}");
        i = i + 1;
    };
    if (crea(10).v > 5) { stdp.println("mayor"); } else if (crea(20).v > 5) { stdp.println("no"); };
    if (crea(1).v > 5) { stdp.println("no"); } else if (crea(30).v > 5) { stdp.println("else if"); };
    return 0;
}
"""))
