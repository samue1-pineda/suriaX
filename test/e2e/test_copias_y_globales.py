"""e2e (intérprete): devolver por valor COPIA, el préstamo mutable
(``at_mut``) y la destrucción de las globales al terminar el programa.

Salen de la caza de fallos (``c_errorstfix.md``, 2e): un struct devuelto por
valor quedaba enlazado al original (``dame().n = 5`` cambiaba la global,
``v.get(0).push(8)`` el vector guardado), y las globales no se destruían
nunca (un ``File`` global no llegaba a escribirse, el ``__free__`` de una
global no corría). Cada prueba compara la salida EXACTA del programa.
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

_PROGRESO = ("frontend OK", "HIR (", "  unidad '")


def _salida(out: str) -> str:
    """Lo que escribió el PROGRAMA: sin las líneas de progreso del driver."""
    return "".join(l + "\n" for l in out.splitlines()
                   if not l.startswith(_PROGRESO))


def _corre(fuente: str, *flags: str) -> tuple:
    """``(código, salida del programa, stderr)`` en el intérprete."""
    code, out, err = run_source(fuente, args=["--run", "interpreter", *flags])
    return code, _salida(out), err


_R = ("#from io #import stdp\n"
      "struct { int id; } R;\n"
      "hook fn __free__(R ptr r) -> void { stdp.println(f\"free {r.id}\"); }\n")


# --------------------------------------------------------------------------- #
# devolver por valor copia
# --------------------------------------------------------------------------- #

def test_lo_devuelto_por_valor_es_una_copia():
    code, out, err = _corre("""\
#from io #import stdp
#import array.vector as vec
struct { int n; } Caja;
struct { Caja c; } Env;
var Caja g = Caja{ n: 1 };
fn dame() -> Caja { return g; }
fn ident(Caja c) -> Caja { return c; }
@impl Caja { fn sube(Caja ptr mutable self) -> void { self.n = self.n + 100; } }
@impl Env { fn copia(Env ptr self) -> Caja { return self.c; } }
fn main() -> int {
    dame().sube();
    stdp.println(f"g={g.n}");
    var Env e = Env{ c: Caja{ n: 10 } };
    e.copia().sube();
    var Caja x = e.copia();
    x.n = 30;
    stdp.println(f"e.c={e.c.n}");
    var Caja l = Caja{ n: 7 };
    ident(l).sube();
    stdp.println(f"l={l.n}");
    var vec.Vector<vec.Vector<int>> vv = vec.dynamic<vec.Vector<int>>(2);
    vv.push(vec.dynamic<int>(2));
    vv.get(0).push(8);
    stdp.println(f"len={vv.get(0).len()}");
    return 0;
}
""")
    assert code == 0, err
    assert out == "g=1\ne.c=10\nl=7\nlen=0\n", out


def test_el_campo_de_un_literal_y_el_payload_de_una_variante_son_copias():
    """``Env{ c: l }`` guarda una copia de ``l``: el literal se devuelve sin
    copiar (es nuevo), así que si su campo compartiera el objeto con ``l``,
    el receptor de un método lo cambiaría."""
    code, out, err = _corre("""\
#from io #import stdp
struct { int n; } Caja;
struct { Caja c; } Env;
enum Forma { Con(Caja), Sin };
@impl Caja { fn sube(Caja ptr mutable self) -> void { self.n = self.n + 1; } }
fn envuelve(Caja c) -> Env { return Env{ c: c }; }
fn main() -> int {
    var Caja l = Caja{ n: 7 };
    Env{ c: l }.c.sube();
    var Forma f = Forma.Con(l);
    match (f) { case Con(k): { k.n = 99; } case Sin: { } }
    stdp.println(f"l={l.n}");
    return 0;
}
""")
    assert code == 0, err
    assert out == "l=7\n", out


def test_ligar_un_enum_con_payload_lo_copia():
    """``var Forma g = f;`` copia el payload, como un struct copia sus
    campos: cambiarlo en un ``case`` sobre ``g`` no toca ``f``."""
    code, out, err = _corre("""\
#from io #import stdp
struct { int n; } Caja;
enum Forma { Con(Caja), Sin };
fn main() -> int {
    var Forma f = Forma.Con(Caja{ n: 1 });
    var Forma g = f;
    match (g) { case Con(k): { k.n = 99; } case Sin: { } }
    match (f) { case Con(k): { stdp.println(f"f={k.n}"); } case Sin: { } }
    match (g) { case Con(k): { stdp.println(f"g={k.n}"); } case Sin: { } }
    return 0;
}
""")
    assert code == 0, err
    assert out == "f=1\ng=99\n", out


def test_lo_lanzado_por_valor_es_una_copia():
    """El ``catch`` recibe lo lanzado por valor, como un ``return``: cambiar
    lo atrapado no toca la global de la que salió."""
    code, out, err = _corre("""\
#from io #import stdp
struct { int n; } Caja;
var Caja g = Caja{ n: 1 };
fn lanza() -> void { throw g; }
fn main() -> int {
    try { lanza(); } catch (Caja c) { c.n = 50; stdp.println(f"c={c.n}"); }
    stdp.println(f"g={g.n}");
    return 0;
}
""")
    assert code == 0, err
    assert out == "c=50\ng=1\n", out


def test_devolver_un_local_con_destructor_lo_mueve_sin_copiarlo():
    """El local muere al salir: devolverlo lo MUEVE y se destruye una vez,
    en el llamador."""
    code, out, err = _corre(_R + """\
fn fabrica() -> R { var R r = R{ id: 1 }; return r; }
fn main() -> int {
    var R a = fabrica();
    stdp.println(f"tengo {a.id}");
    return 0;
}
""")
    assert code == 0, err
    assert out == "tengo 1\nfree 1\n", out


# --------------------------------------------------------------------------- #
# el préstamo mutable: at_mut
# --------------------------------------------------------------------------- #

def test_at_mut_modifica_el_elemento_guardado():
    code, out, err = _corre("""\
#from io #import stdp
#import array.vector as vec
#import collections.dictionary as dic
struct { int n; } Caja;
@impl Caja { fn sube(Caja ptr mutable self) -> void { self.n = self.n + 100; } }
fn main() -> int {
    var vec.Vector<Caja> cs = vec.dynamic<Caja>(2);
    cs.push(Caja{ n: 1 });
    cs.push(Caja{ n: 2 });
    cs.at_mut(0).n = 42;
    cs.at_mut(0).sube();
    cs.at_mut(1).n = 7;
    var vec.Vector<vec.Vector<int>> vv = vec.dynamic<vec.Vector<int>>(2);
    vv.push(vec.dynamic<int>(2));
    vv.at_mut(0).push(9);
    vv.at_mut(0).push(10);
    vv.at_mut(0)[0] = 99;
    var dic.Dictionary<str, vec.Vector<int>> d = dic.make<str, vec.Vector<int>>(4);
    d.put("a", vec.dynamic<int>(1));
    d.put("b", vec.dynamic<int>(1));
    d.at_mut("a").push(1);
    d.at_mut("a").push(2);
    d.at_mut("b").push(5);
    var str k = "a";
    var str kb = "b";
    stdp.println(f"{cs[0].n} {cs[1].n} {vv[0].len()} {vv[0][0]} {vv[0][1]}");
    stdp.println(f"{d.get(k).len()} {d.get(kb).len()}");
    return 0;
}
""")
    assert code == 0, err
    assert out == "142 7 2 99 10\n2 1\n", out


def test_at_mut_comprueba_el_rango_y_la_clave():
    """Con elementos struct: prestar un elemento ESCALAR ('at_mut' sobre un
    'Vector<int>') ya no compila (SEM013), porque ningún motor sabe prestarlo
    y era RT011 al ejecutar."""
    code, out, err = _corre("""\
#from io #import stdp
#import array.vector as vec
#import collections.dictionary as dic
#import excepciones as exc
struct { int n; } Caja;
fn main() -> int {
    var vec.Vector<Caja> v = vec.dynamic<Caja>(4);
    v.push(Caja{ n: 1 });
    try { v.at_mut(1); } catch (str m) { stdp.println(m); }
    var dic.Dictionary<str, Caja> d = dic.make<str, Caja>(4);
    try { d.at_mut("no"); } catch (exc.NoEncontrado e) { stdp.println("no está"); }
    return 0;
}
""")
    assert code == 0, err
    assert out == "at_mut fuera de rango\nno está\n", out


def test_el_prestamo_de_at_mut_muere_si_el_vector_crece():
    """Un ``push`` sobre un vector lleno lo mueve a otro bloque: el puntero
    de antes apunta a una celda liberada (RT003), como dice su comentario."""
    code, out, err = _corre("""\
#from io #import stdp
#import array.vector as vec
struct { int n; } Caja;
fn main() -> int {
    var vec.Vector<Caja> cs = vec.dynamic<Caja>(1);
    cs.push(Caja{ n: 1 });
    var Caja ptr mutable p = cs.at_mut(0);
    p.n = 5;
    stdp.println(f"{cs[0].n}");
    cs.push(Caja{ n: 2 });
    p.n = 6;
    return 0;
}
""")
    assert code == 70, (code, out, err)
    assert out == "5\n", out
    assert "RT003" in err and "(11:5)" in err, err


def test_el_prestamo_de_at_mut_muere_si_el_diccionario_crece():
    code, out, err = _corre("""\
#import collections.dictionary as dic
struct { int n; } Caja;
fn main() -> int {
    var dic.Dictionary<int, Caja> d = dic.make<int, Caja>(1);
    d.put(0, Caja{ n: 1 });
    var Caja ptr mutable p = d.at_mut(0);
    var int i = 1;
    while (i < 20) { d.put(i, Caja{ n: i }); i = i + 1; }
    p.n = 6;
    return 0;
}
""")
    assert code == 70, (code, out, err)
    assert "RT003" in err and "(9:5)" in err, err


# --------------------------------------------------------------------------- #
# las globales mueren al terminar el programa
# --------------------------------------------------------------------------- #

def test_las_globales_mueren_al_volver_de_main_en_orden_inverso():
    code, out, err = _corre(_R + """\
struct { R r; int k; } Par;
var R a = R{ id: 1 };
var Par p = Par{ r: R{ id: 2 }, k: 0 };
var R b = R{ id: 3 };
fn main() -> int {
    var R l = R{ id: 10 };
    b = R{ id: 4 };
    stdp.println("fin main");
    return 0;
}
""")
    assert code == 0, err
    assert out == "free 3\nfin main\nfree 10\nfree 4\nfree 2\nfree 1\n", out


def test_una_global_movida_no_se_destruye():
    code, out, err = _corre(_R + """\
var R g = R{ id: 1 };
var R h = R{ id: 2 };
fn entrega() -> R { return move g; }
fn main() -> int {
    var R x = entrega();
    stdp.println(f"tengo {x.id}");
    return 0;
}
""")
    assert code == 0, err
    assert out == "tengo 1\nfree 1\nfree 2\n", out


def test_las_globales_de_un_guion_sin_main_mueren_al_terminar():
    code, out, err = _corre(_R + """\
var R a = R{ id: 1 };
var R b = R{ id: 2 };
stdp.println("guion");
""")
    assert code == 0, err
    assert out == "guion\nfree 2\nfree 1\n", out


def test_las_globales_de_una_libreria_mueren_despues_que_las_del_programa():
    """La librería se inicializó primero: un global del programa puede
    depender de uno suyo (lo usa su destructor), y al revés no."""
    lib = ("#from io #import stdp\n"
           "public struct { str nombre; } Recurso;\n"
           # el hook NO va en la línea 3, donde está el '__free__' del
           # programa: hoy dos hooks del mismo nombre en la misma línea de
           # unidades distintas se confunden (anotado en c_errorstfix.md)
           "\n"
           "hook fn __free__(Recurso ptr r) -> void "
           "{ stdp.println(f\"free lib {r.nombre}\"); }\n"
           "var Recurso uno = Recurso{ nombre: \"uno\" };\n"
           "var Recurso dos = Recurso{ nombre: \"dos\" };\n"
           "public fn hola() -> void { stdp.println(\"hola lib\"); }\n"
           "#export as reg\n")
    main = (_R + "#import reg\n"
             "var R a = R{ id: 1 };\n"
             "fn main() -> int { reg.hola(); stdp.println(\"fin main\"); "
             "return 0; }\n")
    code, out, err = run_project({"lib/reg.libsrx": lib, "main.srcx": main},
                                 args=["--run", "interpreter"])
    assert code == 0, err
    assert _salida(out) == ("hola lib\nfin main\nfree 1\nfree lib dos\n"
                            "free lib uno\n"), out


def test_un_destructor_que_lee_una_global_ya_destruida_es_rt003():
    """``a`` se declaró antes que ``b``, así que muere después: su destructor
    ya no puede leer ``b``. Se dice (RT003), no se lee un valor muerto."""
    code, out, err = _corre("""\
#from io #import stdp
struct { int id; } R;
struct { int id; } Usa;
hook fn __free__(R ptr r) -> void { stdp.println(f"free {r.id}"); }
hook fn __free__(Usa ptr u) -> void { stdp.println(f"usa lee {b.id}"); }
var Usa a = Usa{ id: 1 };
var R b = R{ id: 2 };
fn main() -> int { return 0; }
""")
    assert code == 70, (code, out, err)
    assert out == "free 2\n", out
    assert "RT003" in err, err


def test_una_global_sin_destructor_sigue_legible_al_destruir_las_demas():
    """Lo que no tiene ningún ``__free__`` dentro no se destruye (como un
    local de ese tipo): el destructor de otra global todavía lo puede leer."""
    code, out, err = _corre("""\
#from io #import stdp
#import array.vector as vec
struct { int id; } Usa;
hook fn __free__(Usa ptr u) -> void { stdp.println(f"cuenta {cuenta} {v.len()}"); }
var Usa a = Usa{ id: 1 };
var int cuenta = 3;
var vec.Vector<int> v = vec.dynamic<int>(2);
fn main() -> int { v.push(1); return 0; }
""")
    assert code == 0, err
    assert out == "cuenta 3 1\n", out


def test_un_destructor_que_lanza_al_terminar_es_rt021():
    code, out, err = _corre("""\
#from io #import stdp
struct { int id; } R;
fn falla() -> void { throw "no se pudo cerrar"; }
hook fn __free__(R ptr r) -> void { falla(); }
var R g = R{ id: 1 };
fn main() -> int { stdp.println("fin main"); return 0; }
""")
    assert code == 70, (code, out, err)
    assert out == "fin main\n", out
    assert "RT021" in err, err


# 'un error que nadie atrapa' y '--test': las reglas nuevas (globales que
# mueren tras un throw/EXC sin atrapar; globales propias de cada prueba) estan
# en 'test_interpreter_termination.py' y 'test_test_runner.py'.


def test_salir_no_destruye_las_globales():
    code, out, err = _corre(_R + """\
#import sistema.proceso as proceso
var R g = R{ id: 1 };
fn main() -> int {
    stdp.println("antes");
    proceso.salir(3);
    return 0;
}
""")
    assert code == 3, (code, out, err)
    assert out == "antes\n", out


def test_la_traza_de_memoria_muestra_la_muerte_de_una_global():
    code, out, err = _corre(_R + "var R g = R{ id: 1 };\n"
                                 "fn main() -> int { return 0; }\n",
                            "--trace-memory")
    assert code == 0, err
    assert "[mem] drop global 'g' (fin del programa)" in out, out


def test_un_archivo_global_se_escribe_al_terminar():
    """El caso de la caza: un ``File`` global no llegaba a escribirse porque
    su ``__free__`` (que vuelca y cierra) no corría nunca."""
    fuente = ("#import sistema.archivos as arch\n"
              "var arch.File log = arch.open(\"salida.txt\", \"w\");\n"
              "fn main() -> int { log.write(\"hola global\\n\"); return 0; }\n")
    with tempfile.TemporaryDirectory(prefix="suriax-test-") as tmp:
        ruta = os.path.join(tmp, "prog.srcx")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(fuente)
        proc = subprocess.run([sys.executable, _V0, ruta, "--run", "interpreter"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", cwd=tmp, timeout=120)
        assert proc.returncode == 0, proc.stderr
        with open(os.path.join(tmp, "salida.txt"), encoding="utf-8") as fh:
            assert fh.read() == "hola global\n"
