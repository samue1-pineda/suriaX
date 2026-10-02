"""backend/vm_diferencial: colecciones y destruccion por tipo de los elementos.

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

def test_collections_dictionary():
    """'collections.Dictionary<K, V>' con claves str, int y struct (con
    '__hash__' y '__eq__'), crecimiento, remove y 'keys()': el orden de las
    claves depende del hash, y los dos motores lo calculan igual."""
    _comparar(_en_linea("""\
#from io #import stdp
#import collections.dictionary as dic
#import excepciones as exc
#import array.vector as vec
struct { int x; int y; } Punto;
hook fn __hash__(Punto ptr p) -> int { return hash(p.x) ^ (hash(p.y) << 1); }
hook fn __eq__(Punto ptr a, Punto ptr b) -> bool { return a.x == b.x and a.y == b.y; }
fn main() -> int {
    var str ANA = "ana";
    var str LUIS = "luis";
    var str HOLA = "hola";
    var dic.Dictionary<str, int> edades = dic.make<str, int>(2);
    edades.put("ana", 31);
    edades.put("luis", 28);
    edades.put("eva", 40);
    edades.put("ana", 32);
    var int i = 0;
    while (i < 20) { edades.put(f"k{i}", i); i = i + 1; };
    stdp.println(f"{edades.len()} {edades.get(ANA)} {edades.contains(LUIS)}");
    edades.remove("luis");
    stdp.println(f"{edades.len()} {edades.contains(LUIS)}");
    try { edades.get("luis"); } catch (exc.NoEncontrado e) { stdp.println(e.mensaje); };
    var dic.Dictionary<Punto, str> nombres = dic.make<Punto, str>(4);
    nombres.put(Punto{ x: 1, y: 2 }, "a");
    nombres.put(Punto{ x: 1, y: 2 }, "b");
    nombres.put(Punto{ x: 3, y: 4 }, "c");
    stdp.println(f"{nombres.len()} {nombres.get(Punto{ x: 1, y: 2 })}");
    var dic.Dictionary<int, char> letras = dic.make<int, char>(4);
    letras.put(1, 'a');
    letras.put(-7, 'z');
    stdp.println(f"{letras.get(-7)} {hash(1)} {hash(HOLA)} {hash('a')} {hash(true)}");
    var vec.Vector<str> claves = edades.keys();
    var vec.Vector<int> valores = edades.values();
    var str todo = "";
    var int j = 0;
    while (j < claves.len()) { todo = todo + f"{claves.get(j)}={valores.get(j)} "; j = j + 1; };
    stdp.println(todo);
    return 0;
}
"""))


def test_destruir_por_tipo_en_los_dos_motores():
    """Lo que el frontend no puede aplanar se destruye POR SU TIPO en los dos
    motores igual: un 'T', un 'catch (e)' sin tipo, el valor viejo de una
    asignacion, un argumento que nadie recibio, las celdas de un bloque y un
    generico con su propio '__free__'. Mismo orden y cero objetos vivos."""
    _comparar(_en_linea("""\
#from io #import stdp
#import mem
#import excepciones as exc
struct { int id; } R;
hook fn __free__(R ptr r) -> void { stdp.println(f"libera {r.id}"); }
struct { T v; } Caja<T>;
hook fn __free__(Caja<T> ptr c) -> void { stdp.println("libera caja"); }
struct { R a; R b; } Par;
fn falla() -> int { throw exc.ValorInvalido{ mensaje: "no" }; }
fn usa(R r, int x) -> int { return r.id + x; }
fn toma<T>(T x) -> int { return 0; }
fn devuelve<T>(T x) -> T { var T y = move x; return y; }
fn guarda<T>(T ptr mutable b, T x) -> void { b[0] = move x; }
var R global = R{ id: 90 };
fn main() -> int {
    try { usa(R{ id: 1 }, falla()); } catch (exc.ValorInvalido e) { stdp.println("a"); };
    try {
        var R a = R{ id: 2 };
        var R r = R{ id: 3 };
        usa(move r, falla());
    } catch (exc.ValorInvalido e) { stdp.println("b"); };
    try {
        var R q = R{ id: 4 };
        var Par p = Par{ a: move q, b: R{ id: falla() } };
    } catch (exc.ValorInvalido e) { stdp.println("c"); };
    try { throw R{ id: 5 }; } catch (e) { stdp.println("d"); };
    try { throw 7; } catch (e) { stdp.println("e"); };
    try { var int cero = 0; var int x = 1 / cero; } catch (e) { stdp.println("f"); };
    toma<R>(R{ id: 6 });
    var R d = devuelve<R>(R{ id: 7 });
    var R a = R{ id: 8 };
    a = R{ id: 9 };
    var Par pp = Par{ a: R{ id: 10 }, b: R{ id: 11 } };
    pp.a = R{ id: 12 };
    global = R{ id: 91 };
    var R ptr mutable b = mem.reserve<R>(2);
    var R c = R{ id: 13 };
    b[0] = move c;
    guarda<R>(b, R{ id: 14 });
    b[1] = R{ id: 15 };
    mem.release<R>(b);
    var Caja<R> k = Caja<R>{ v: R{ id: 16 } };
    stdp.println("fin");
    return 0;
}
"""))


def test_los_contenedores_destruyen_sus_elementos_en_los_dos_motores():
    """'Vector<R>', 'Vector<Vector<R>>' y 'Dictionary<str, R>': destruyen al
    morir, al reemplazar y al quitar; 'take', 'pop' y 'at' no. Tambien una
    lista enlazada de bloques, larga, y un '__free__' generico."""
    _comparar(_en_linea("""\
#from io #import stdp
#import mem
#import array.vector as vec
#import collections.dictionary as dic
struct { int id; } R;
hook fn __free__(R ptr r) -> void { stdp.println(f"libera {r.id}"); }
struct { R dato; Nodo ptr mutable sig; } Nodo;
fn main() -> int {
    var vec.Vector<R> v = vec.dynamic<R>(1);
    var int i = 0;
    while (i < 5) { v.push(R{ id: i }); i = i + 1; };
    stdp.println(f"at {v.at(3).id}");
    v.set(0, R{ id: 50 });
    var R sacado = v.take(1);
    var R ultimo = v.pop();
    stdp.println(f"{sacado.id} {ultimo.id} {v.len()}");
    var vec.Vector<vec.Vector<R>> vv = vec.dynamic<vec.Vector<R>>(1);
    var vec.Vector<R> f1 = vec.dynamic<R>(1);
    f1.push(R{ id: 20 });
    f1.push(R{ id: 21 });
    vv.push(move f1);
    var vec.Vector<R> f2 = vec.dynamic<R>(1);
    f2.push(R{ id: 22 });
    vv.push(move f2);
    stdp.println(f"{vv.at(1).at(0).id}");
    var dic.Dictionary<str, R> d = dic.make<str, R>(2);
    i = 0;
    while (i < 12) { d.put(f"k{i}", R{ id: 100 + i }); i = i + 1; };
    d.put("k3", R{ id: 200 });
    d.remove("k4");
    var R t = d.take("k5");
    stdp.println(f"{d.len()} {d.at("k3").id} {t.id}");
    var Nodo ptr mutable cab = mem.reserve<Nodo>(1);
    cab[0] = Nodo{ dato: R{ id: 300 }, sig: mem.reserve<Nodo>(0) };
    var Nodo ptr mutable actual = cab;
    i = 0;
    while (i < 50) {
        var Nodo ptr mutable nuevo = mem.reserve<Nodo>(1);
        nuevo[0] = Nodo{ dato: R{ id: 301 + i }, sig: mem.reserve<Nodo>(0) };
        mem.release<Nodo>(actual[0].sig);
        actual[0].sig = nuevo;
        actual = nuevo;
        i = i + 1;
    };
    mem.release<Nodo>(cab);
    stdp.println("fin");
    return 0;
}
"""))


def test_un_free_que_lanza_desde_un_contenedor_es_rt021_en_los_dos():
    _comparar(_en_linea("""\
#from io #import stdp
#import array.vector as vec
struct { int id; } Q;
fn lanza() -> void { throw "no"; }
hook fn __free__(Q ptr q) -> void { lanza(); }
fn main() -> int {
    var vec.Vector<Q> v = vec.dynamic<Q>(1);
    v.push(Q{ id: 1 });
    stdp.println("antes");
    return 0;
}
"""))
