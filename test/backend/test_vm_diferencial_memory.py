"""backend/vm_diferencial: la memoria de la VM (liberacion, cadenas, celdas, nullables).

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

def test_la_vm_libera_todo_lo_que_crea():
    """Los casos donde un objeto cambia de dueño o muere por un camino raro:
    un vector de structs que crece, vectores anidados que se copian, un
    struct que se reasigna, temporales en la condición de un 'while', un
    'return' desde un 'catch', un 'catch (e)' sin tipo y un 'free' explícito.
    El diferencial exige además cero objetos vivos al terminar."""
    _comparar(_en_linea("""\
#from io #import stdp
#import array.vector as vec
#import excepciones as exc
struct { int v; } C;
struct { C a; vec.Vector<C> lista; } Caja;
fn crea(int n) -> C { return C{ v: n }; }
fn busca(vec.Vector<C> ptr v, int x) -> int {
    try {
        if (x >= v.len()) { throw exc.NoEncontrado{ mensaje: "no" }; };
        return v.get(x).v;
    } catch (exc.NoEncontrado e) {
        return -1;
    };
}
fn main() -> int {
    var vec.Vector<C> v = vec.dynamic<C>(1);
    var int i = 0;
    while (i < 20) { v.push(crea(i)); i = i + 1; };
    var vec.Vector<vec.Vector<C>> filas = vec.dynamic<vec.Vector<C>>(1);
    filas.push(v);
    filas.push(v);
    var vec.Vector<C> copia = filas.get(1);
    copia.push(C{ v: 99 });
    var Caja k = Caja{ a: crea(1), lista: v };
    k.a = crea(2);
    k.lista = copia;
    var int n = 0;
    while (crea(n).v < 3) { n = n + 1; };
    try { throw C{ v: 5 }; } catch (e) { stdp.println("atrapado sin tipo"); };
    var C suelto = crea(7);
    free &suelto;
    stdp.println(f"{v.len()} {filas.len()} {copia.len()} {k.lista.len()} {k.a.v} {n} {busca(&v, 3)} {busca(&v, 50)}");
    return 0;
}
"""))


def test_la_vm_recoge_las_cadenas_sin_perder_las_vivas():
    """Miles de cadenas temporales (más que el umbral del barrido, así que se
    recoge varias veces y se REUTILIZAN huecos) mientras otras siguen vivas
    dentro de un vector y en variables. Si el barrido soltara una viva, la
    salida cambiaría o la VM fallaría al leerla."""
    _comparar(_en_linea("""\
#from io #import stdp
#import array.vector as vec
fn main() -> int {
    var vec.Vector<str> guardadas = vec.dynamic<str>(4);
    var str acumulada = "";
    var int i = 0;
    while (i < 12000) {
        var str temporal = f"cadena numero {i}";
        if (i % 1000 == 0) {
            guardadas.push(temporal);
            acumulada = acumulada + f"[{i}]";
        };
        i = i + 1;
    };
    var int j = 0;
    while (j < guardadas.len()) {
        stdp.println(guardadas.get(j));
        j = j + 1;
    };
    stdp.println(acumulada);
    return 0;
}
"""))


def test_un_escalar_por_direccion_vive_en_una_celda():
    """'&n' sobre un escalar: el local, el parametro o la global pasa a una
    CELDA del monton (su handle es la direccion y 'p[0]' la lee), y la celda
    muere con su ambito. Antes el MIR lo rechazaba."""
    _comparar(_en_linea("""\
#from io #import stdp
var int contador = 0;
fn inc(int ptr mutable p) -> void { p[0] = p[0] + 1; }
fn suma_en(float ptr mutable p, float d) -> void { p[0] = p[0] + d; }
fn por_parametro(int n) -> int {
    var int ptr mutable q = &n;
    q[0] = q[0] + 10;
    return n;
}
fn main() -> int {
    var int n = 1;
    inc(&n);
    inc(&n);
    inc(&contador);
    var float w = 1.0;
    var int i = 0;
    while (i < 3) {
        suma_en(&w, 0.5);
        var int local = i;
        var int ptr r = &local;
        stdp.println(f"{r[0]} {w}");
        i = i + 1;
    };
    var str s = "hola";
    var str ptr ps = &s;
    stdp.println(f"{n} {contador} {por_parametro(5)} {ps[0]}");
    return 0;
}
"""))


def test_un_nullable_de_un_escalar_es_una_celda():
    """'int?', 'float?', 'bool?', 'char?': el valor es una celda (o -1,
    null). Un escalar que entra donde se espera un 'T?' se encaja; '=='
    compara lo que guardan; en un vector, un campo o un payload se copia y
    se libera con su dueño."""
    _comparar(_en_linea("""\
#from io #import stdp
#import array.vector as vec
struct { int? edad; float? peso; } Ficha;
enum Op { Nada, Algo(int?), Doble(float?, char?) };
var int? global_n;
var float? global_f = 2.5;
fn toma(int? x) -> int? {
    if (x == null) { return null; };
    return 4;
}
fn main() -> int {
    var vec.Vector<int?> v = vec.dynamic<int?>(2);
    var int k = 3;
    v.push(1);
    v.push(null);
    v.push(k);
    var Ficha f = Ficha{ edad: 7, peso: null };
    var Ficha g = f;
    g.edad = 8;
    f.peso = 60.5;
    var int? sin_valor;
    var float? x = 0.1;
    var float? y = 0.1;
    global_n = 12;
    stdp.println(f"{v.get(0)} {v.get(1)} {v.get(2)} {f.edad} {g.edad} {f.peso} {g.peso}");
    stdp.println(f"{toma(null)} {toma(k)} {toma(5) == 4} {sin_valor}");
    stdp.println(f"{Op.Algo(9)} {Op.Doble(null, 'q')} {Op.Algo(null)} {Op.Nada}");
    stdp.println(f"{global_n} {global_f} {x == y} {x != null} {x == 0.1}");
    var bool? t = true;
    var char? c = 'z';
    stdp.println(f"{t} {c}");
    return 0;
}
"""))
