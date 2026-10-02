"""backend/vm_diferencial: llamadas al host (lib/sistema), flotantes, paquetes y structs como valor.

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

# --------------------------------------------------------------------------- #
# llamadas al host: lib/sistema
# --------------------------------------------------------------------------- #

def _con_archivos(fuente: str, archivos: dict):
    """Como ``_en_linea``, con archivos de apoyo (nombre -> bytes)."""
    def preparar(tmp: str) -> str:
        for nombre, contenido in archivos.items():
            ruta = os.path.join(tmp, nombre)
            os.makedirs(os.path.dirname(ruta), exist_ok=True)
            with open(ruta, "wb") as fh:
                fh.write(contenido)
        return _en_linea(fuente)(tmp)
    return preparar


def test_sistema_lee_escribe_lista_y_recibe_argumentos():
    """Mismo contrato en los dos motores: UTF-8 sin traducir los fines de
    línea, listado ordenado y los argumentos de después de '--'."""
    _comparar(_con_archivos("""#from io #import stdp
#import sistema.archivos as arch
#import sistema.proceso as proc
#import array.vector as vec
fn main() -> int {
    stdp.println(f"{proc.argumentos()} argumentos");
    var int i = 1;
    while (i < proc.argumentos()) {
        stdp.println(f"  {i}: {proc.argumento(i)}");
        i = i + 1;
    };
    var str t = arch.leer("datos/entrada.txt");
    stdp.println(f"{len(t)} caracteres; el 5 es '{t[5]}'");
    arch.escribir("copia.txt", t + "fin\\r\\n");
    stdp.println(f"la copia mide {len(arch.leer("copia.txt"))}");
    stdp.println(f"{arch.existe("copia.txt")} {arch.existe("no_esta.txt")} {arch.existe("datos")}");
    var vec.Vector<str> nombres = arch.listar("datos");
    var int j = 0;
    while (j < nombres.len()) {
        stdp.println(f"  - {nombres.get(j)}");
        j = j + 1;
    };
    return proc.argumentos();
}
""", {"datos/entrada.txt": "línea\r\nañ日\n".encode("utf-8"),
      "datos/b.txt": b"", "datos/a.txt": b"", "datos/Zeta.txt": b""}),
             argumentos=("uno", "dos tres", "--no-es-del-compilador"))


def test_sistema_los_fallos_de_archivo_son_errordearchivo():
    """EXC003 con el MISMO mensaje en los dos motores: no existe, es una
    carpeta, no es UTF-8, no es una carpeta. Un argumento que no existe es
    EXC002, y si nadie lo atrapa el programa termina con ese código."""
    _comparar(_con_archivos("""#from io #import stdp
#import sistema.archivos as arch
#import sistema.proceso as proc
#import excepciones as exc
#import array.vector as vec
fn prueba(str ruta) -> void {
    try {
        var str t = arch.leer(ruta);
        stdp.println(f"leyó {len(t)}");
    } catch (exc.ErrorDeArchivo e) {
        stdp.println(e.mensaje);
    };
}
fn main() -> int {
    prueba("no_esta.txt");
    prueba("carpeta");
    prueba("binario.dat");
    try {
        var vec.Vector<str> v = arch.listar("binario.dat");
    } catch (exc.ErrorDeArchivo e) {
        stdp.println(e.mensaje);
    };
    try {
        var vec.Vector<str> v = arch.listar("tampoco");
    } catch (exc.ErrorDeArchivo e) {
        stdp.println(e.mensaje);
    };
    stdp.println(proc.argumento(7));
    return 0;
}
""", {"carpeta/x.txt": b"x", "binario.dat": b"\xff\xfe\x00a"}))


def test_sistema_salir_termina_sin_desenrollar():
    """'salir' termina AHORA con su código: lo ya impreso se ve, lo que
    seguía no, y el '__free__' pendiente no corre."""
    _comparar(_en_linea("""#from io #import stdp
#import sistema.archivos as arch
#import sistema.proceso as proc
struct { int id; } R;
hook fn __free__(R ptr r) -> void { stdp.println(f"drop {r.id}"); }
fn main() -> int {
    var R r = R{ id: 1 };
    stdp.println("antes");
    proc.salir(5);
    stdp.println("no se ve");
    return 0;
}
"""))


def test_un_float_se_escribe_como_en_el_interprete():
    """Los MENOS dígitos que reproducen el valor, y científica fuera de
    [1e-4, 1e16): antes la VM escribía 17 dígitos fijos y PI salía
    '3.1415926535897931'."""
    _comparar(_en_linea("""#from io #import stdp
fn main() -> int {
    var float cero = 0.0;
    stdp.println(f"{3.141592653589793} {0.1} {0.1 + 0.2} {4.0} {100.0} {0.0}");
    stdp.println(f"{10000000000000000.0} {1000000000000000.0} {123456789012345678.0}");
    stdp.println(f"{0.0001} {0.00001} {0.00000015} {0.0 - 0.000025}");
    stdp.println(f"{0.0 - 2.5} {cero - 0.0} {1.0 / 3.0} {2.0 / 3.0}");
    stdp.println(f"{1.0 / cero} {(0.0 - 1.0) / cero} {cero / cero}");
    return 0;
}
"""))


def test_un_paquete_importado_entero_se_recorre_por_su_ruta():
    """'#import math' y luego 'math.constants.PI': la unidad son VARIOS
    tramos de la ruta. La VM solo traducía un alias de un tramo y dejaba la
    llamada 'SIN RESOLVER'."""
    _comparar(_en_linea("""\
#import IO
#import math
#import sistema
fn main() -> int {
    var bool hay = sistema.archivos.existe("prog.srcx");
    IO.stdp.println(f"{hay} {sistema.proceso.argumentos()}");
    IO.stdp.println(f"{math.constants.PI} {math.basic.max(2.0, 3.5)}");
    return 0;
}
"""))


def test_un_struct_es_un_valor_en_los_dos_motores():
    """Ligar, asignar, pasar por valor, meter en un campo o devolver un campo
    COPIA, en profundidad. La VM compartía el objeto en todos esos casos (un
    handle copiado es el mismo objeto): 'b.v = 99' cambiaba 'a', y una
    función que mutaba su parámetro mutaba al llamador."""
    _comparar(_en_linea("""#from io #import stdp
struct { int v; } C;
struct { C dentro; int k; } D;
fn cambia(C x) -> int { x.v = 7; return x.v; }
fn saca(D ptr d) -> C { return d.dentro; }
fn main() -> int {
    var C a = C{ v: 1 };
    var C b = a;
    b.v = 99;
    var int r = cambia(a);
    var D d = D{ dentro: a, k: 1 };
    var D e = d;
    e.dentro.v = 50;
    var C f = d.dentro;
    f.v = 500;
    var C g = saca(&d);
    g.v = 5000;
    var C h = C{ v: 0 };
    h = a;
    h.v = 3;
    d.dentro = h;
    d.dentro.v = 4;
    stdp.println(f"{a.v} {b.v} {r} {d.dentro.v} {e.dentro.v} {f.v} {g.v} {h.v}");
    return 0;
}
"""))


# --------------------------------------------------------------------------- #
# lib/sistema/rutas: 'os.path' tal cual, en los dos motores
# --------------------------------------------------------------------------- #

#: rutas que cubren cada rama de 'ntpath'/'posixpath': relativas, absolutas,
#: unidad con y sin raiz, UNC, '..' que sobra, separadores repetidos, al final
#: y mezclados, y texto no ASCII
_RUTAS = ["", ".", "..", "a", "a/b", "a\\b", "a/./b/../c", "/a/b/", "a//b//",
          "../a", "a/..", "a/../..", "/..", "C:\\x\\..\\y", "C:x", "C:", "C:/",
          "\\\\srv\\recurso\\x\\..", "//a", "///a", "lib/calc.libsrx",
          "ñandú/ç/../é", "a/b/"]


def test_las_rutas_son_las_de_os_path():
    """La VM reimplementa 'os.path' (ver backend/src/rutas.cpp) y el
    intérprete lo usa tal cual: si los dos motores escriben lo mismo, la VM
    calcula lo que calcula Python en este sistema. Es lo que necesita el
    compilador escrito en suriaX para escribir las mismas rutas que la V0."""
    # dentro de un literal de suriaX una '\' se escribe '\\'
    todas = "|".join(_RUTAS).replace("\\", "\\\\")
    _comparar(_con_archivos(f"""#from io #import stdp
#import sistema.rutas as rt
#import array.vector as vec

fn main() -> int {{
    var vec.Vector<str> rutas = vec.dynamic<str>(32);
    const str todas = "{todas}";
    var int desde = 0;
    var int i = 0;
    while (i <= len(todas)) {{
        if (i == len(todas) or todas[i] == '|') {{
            var str r = "";
            var int k = desde;
            while (k < i) {{ r = r + cast<str>(todas[k]); k = k + 1; }};
            rutas.push(r);
            desde = i + 1;
        }};
        i = i + 1;
    }};
    stdp.println(f"sep={{rt.separador()}} cwd_abs={{rt.absoluta(".") == rt.directorio_actual()}}");
    stdp.println(f"entorno={{rt.entorno("SURIAX_PRUEBA_RUTAS")}}|{{rt.entorno("NO_EXISTE_JAMAS")}}|");
    i = 0;
    while (i < rutas.len()) {{
        const str r = rutas.get(i);
        stdp.println(f"[{{r}}] norm=[{{rt.normaliza(r)}}] abs=[{{rt.absoluta(r)}}] "
                     + f"dir=[{{rt.carpeta_de(r)}}] base=[{{rt.nombre_de(r)}}] "
                     + f"une=[{{rt.une(r, "x.y")}}|{{rt.une("base", r)}}]");
        i = i + 1;
    }};
    stdp.println(f"carpeta={{rt.es_carpeta("datos")}} {{rt.es_carpeta("datos/f.txt")}} "
                 + f"archivo={{rt.es_archivo("datos/f.txt")}} {{rt.es_archivo("datos")}} "
                 + f"{{rt.es_archivo("no_existe")}}");
    return 0;
}}
""", {"datos/f.txt": b"x"}))
