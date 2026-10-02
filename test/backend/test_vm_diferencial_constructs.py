"""backend/vm_diferencial: construcciones sueltas que el corpus no toca.

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

def test_un_cast_de_ancho_fijo_trunca_y_redondea_como_el_interprete():
    """Los '__cast__' PROTOTIPO de 'dt_variables' los pone la máquina: antes
    el MIR dejaba pasar el valor y 'cast<dt.int8>(300)' daba 300."""
    _comparar(_en_linea("""\
#from io #import stdp
#import d_types.dt_variables as dt
fn main() -> int {
    stdp.println(f"{cast<int>(cast<dt.int8>(300))} {cast<int>(cast<dt.int8>(128))}");
    stdp.println(f"{cast<int>(cast<dt.int16>(70000))} {cast<int>(cast<dt.int32>(3000000000))}");
    stdp.println(f"{cast<float>(cast<dt.float16>(0.1))} {cast<float>(cast<dt.float32>(0.1))}");
    stdp.println(f"{cast<float>(cast<dt.float16>(70000.0))} {sizeof(dt.int8)} {sizeof(dt.int32)}");
    return cast<int>(cast<dt.int8>(-129));
}
"""))


def test_un_char_no_ascii_vale_su_punto_de_codigo():
    """El HIR trae el 'char' en UTF-8: tomar su primer byte daba 0xC3."""
    _comparar(_en_linea("""\
#from io #import stdp
fn main() -> int {
    var char c = 'ñ';
    var str s = "año";
    stdp.println(f"{c} {s[1]} {len(s)}");
    if (s[1] == c) { return cast<int>(c) - 200; };
    return 0;
}
"""))


def test_indexar_fuera_de_una_cadena_es_la_excepcion_del_programa():
    """'s[9]' lanza 'excepciones.IndiceFueraDeRango' (EXC002), que se atrapa;
    antes la VM abortaba."""
    _comparar(_en_linea("""\
#from io #import stdp
#import excepciones as exc
fn main() -> int {
    var str s = "hola";
    try {
        var char c = s[9];
        stdp.println(f"no llega {c}");
    } catch (exc.IndiceFueraDeRango e) {
        stdp.println(f"atrapado: {e.mensaje}");
        return 7;
    };
    return 0;
}
"""))


def test_la_igualdad_de_structs_usa_su_eq():
    """'a == b' entre structs con '__eq__' lo decide el hook; antes la VM
    comparaba handles y dos puntos iguales salían distintos."""
    _comparar(_en_linea("""\
struct { int x; } P;
hook fn __eq__(P ptr a, P ptr b) -> bool { return a.x == b.x; }
fn main() -> int {
    var P a = P{ x: 1 };
    var P b = P{ x: 1 };
    var P c = P{ x: 2 };
    var int r = 0;
    if (a == b) { r = r + 10; };
    if (a != c) { r = r + 1; };
    return r;
}
"""))


def test_dos_llamadas_anidadas_en_un_fstring_no_se_confunden():
    """Dentro de un f-string todas las llamadas llevan la posición del
    f-string: el sitio de llamada se identifica por su NODO, no por (línea,
    columna). Antes 'doble(mas_uno(3))' llamaba dos veces a la misma."""
    _comparar(_en_linea("""\
#from io #import stdp
fn doble(int x) -> int { return 2 * x; }
fn mas_uno(int x) -> int { return x + 1; }
fn main() -> int {
    stdp.println(f"{doble(mas_uno(3))} {mas_uno(doble(3))}");
    return doble(mas_uno(3));
}
"""))


def test_un_struct_nullable_viaja_como_handle_con_null():
    _comparar(_en_linea("""\
struct { int v; } Caja;
fn busca(int n) -> Caja? {
    if (n > 0) { return Caja{ v: n }; };
    return null;
}
fn main() -> int {
    var Caja? a = busca(5);
    var Caja? b = busca(0);
    var int r = 0;
    if (a != null) { r = r + a.v; };
    if (b == null) { r = r + 100; };
    return r;
}
"""))


def test_un_temporal_muere_al_cerrar_su_sentencia():
    """Un valor que posee recursos y que nadie recibe se destruye al terminar
    la sentencia; la VM lo ignoraba y el '__free__' no corría nunca."""
    _comparar(_en_linea("""\
#from io #import stdp
struct { int id; } R;
hook fn __free__(R ptr r) -> void { stdp.println(f"drop {r.id}"); }
fn crear(int id) -> R { var R t = R{ id: id }; return t; }
fn main() -> int {
    crear(1);
    stdp.println("despues");
    var int i = 0;
    while (i < 2) {
        crear(10 + i);
        i = i + 1;
    };
    return 0;
}
"""))


def test_un_temporal_se_destruye_aunque_la_sentencia_lance():
    _comparar(_en_linea("""\
#from io #import stdp
struct { int id; } R;
hook fn __free__(R ptr r) -> void { stdp.println(f"drop {r.id}"); }
fn crear(int id) -> R { var R t = R{ id: id }; return t; }
fn lanza(int x) -> int {
    if (x > 0) { throw x; };
    return 0;
}
fn main() -> int {
    try {
        stdp.println(f"{crear(3).id} {lanza(1)}");
    } catch (int e) {
        stdp.println(f"atrapado {e}");
    };
    return 0;
}
"""))
