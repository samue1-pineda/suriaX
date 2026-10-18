"""Lo compartido por los ``test_backend_cpp_*.py`` (antes un solo archivo,
``test_backend_cpp.py``, partido por tema). Aqui van los imports, las constantes y los
helpers; cada modulo de pruebas importa lo que usa.

backend/backend_cpp — prueba DIFERENCIAL: lector de HIR en C++ vs. el de Python.

Un solo `.phir`, dos lectores escritos en lenguajes distintos:

    python  -> runtime.interpreter.loader + V0/src/HIR/pretty.py
    C++     -> build/bin/suriax-hir --pretty / --summary

Si los dos no producen EXACTAMENTE el mismo texto, uno de los dos está
interpretando el contrato a su manera — y eso es un bug del contrato, no del
consumidor. Es la Capa 5 de ``compiler-ir-testing`` (diferencial ENTRE
consumidores), la misma garantía que ``test_web_wasm.py`` da entre el
intérprete y WebAssembly.

La identidad byte a byte es deliberada. Una vista "parecida" no probaría
nada: el diferencial solo sirve mientras la comparación sea exacta.

El programa de referencia toca CADA forma del esquema al menos una vez
(Capa 6): las dos formas de ``enum``, hooks de las tres clases, tipos
envueltos, `move`/`free`/`&`, `try` con ramas filtradas y sin filtrar,
interpolación, `cast`, `sizeof`, bloque `test`, `#extern cpp` y la
destrucción que el compilador INSERTA (drops de ámbito y de campo,
`transfers` del retorno, drop del temporal). Es más barato de mantener que N
programas pequeños y falla antes.

Se OMITE (``helpers.omitir``, visible en el resumen) si el binario no está
construido: el frontend no depende del backend nativo. El HIR ya no necesita
protobuf para emitirse, así que eso no es motivo de omisión.

    cmake -S . -B build && cmake --build build --target suriax-hir
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

# helpers.omitir: la única forma de saltarse una prueba (el runner la cuenta
# como OMITIDA, nunca como pasada).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import omitir  # noqa: E402

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_V0_ROOT = os.path.join(_REPO_ROOT, "V0")
_COMPILER = os.path.join(_V0_ROOT, "main.py")

#: dónde deja CMake el CLI del lector (`RUNTIME_OUTPUT_DIRECTORY`).

#: Programa de REFERENCIA: toca cada forma del esquema al menos una vez.
#: Ampliarlo es la forma de estrenar una construcción nueva en este
#: diferencial — si el emisor la escribe y el lector C++ no la entiende, la
#: prueba lo dice el mismo día.
_REFERENCIA = """\
#from io #import stdp
#import d_types.dt_variables as dt

struct { int x; int y; } Punto;

enum Color { ROJO, VERDE = 5, AZUL };

enum Dato { Vacio, Numero(int), Texto(str) };

hook fn __print__(Punto ptr p) -> void {
    stdp.println("punto");
}

struct { int id; } Recurso;

hook fn __free__(Recurso ptr r) -> void {
    stdp.println("libera");
}

fn fabrica() -> Recurso {
    var Recurso nuevo = Recurso{ id: 7 };
    return nuevo;
}

fn area(Punto ptr p) -> int {
    return p.x * p.y;
}

fn puede_fallar(int n) -> error int {
    if (n < 0) {
        throw "negativo";
    }
    return n;
}

fn main() -> int {
    var Punto p = Punto{ x: 3, y: 4 };
    const int a = area(&p);
    var float f = 2.5;
    var bool listo = true;
    var char c = 'z';
    var str nombre = "suriaX";
    var int? quiza = null;

    // 'len' e indexado sobre un 'str': hooks NATIVOS del lenguaje. Viajan
    // como HookRef con dueño 'str', pero ninguna unidad los declara (SEM006
    // prohibe colgarle hooks a un primitivo), asi que el backend tiene que
    // reconocerlos como suyos y no como un destino que le falta.
    var int largo = len(nombre);
    var char inicial = nombre[0];

    var int contador = 0;
    while (contador < 3) {
        contador += 1;
        if (contador == 1) {
            continue;
        } else if (contador == 2) {
            contador = contador + 0;
        } else {
            break;
        }
    }

    match (contador) {
        case 3: { stdp.println("tres"); }
        case 9: { stdp.println("nueve"); }
    }

    stdp.println(f"area {a} de {nombre}");
    stdp.println(cast<str>(a));

    dt.int8 chico = 0;
    var int tam = sizeof(p);

    try {
        var int r = puede_fallar(-1);
    } catch (str e) {
        stdp.println("filtrado");
    } catch (otro) {
        stdp.println("resto");
    }

    print(p);

    var Punto origen = Punto{ x: 1, y: 1 };
    var Punto destino = Punto{ x: 1, y: 1 };
    move origen;

    var Punto ptr mutable pm = &destino;
    pm.x = 9;
    free pm;

    // la destrucción que INSERTA el compilador: el drop del ámbito, el
    // 'transfers' del retorno y el temporal que nadie recibe.
    var Recurso propio = Recurso{ id: 1 };
    fabrica();

    return a - 12;
}

test "el area sale de los campos" {
    var Punto q = Punto{ x: 2, y: 5 };
    stdp.println("probando");
    expect (q.x == 2);
}

#extern cpp{
int ayuda_nativa() { return 1; }
}
"""


def _binario() -> str | None:
    """El CLI del lector C++, o ``None`` si nadie lo ha construido."""
    from helpers import hir_binary
    return hir_binary()


def _enlaza_lib(destino: str) -> None:
    """La ``lib/`` del repositorio dentro de ``destino`` (ver ``link_lib``)."""
    from helpers import link_lib
    link_lib(destino)


def _compilar(destino: str) -> str:
    """Compila el programa de referencia dentro de ``destino`` y devuelve el
    ``.phir``, con sus unidades ``.libsrx`` al lado (viajan juntas)."""
    # El .srcx tiene que estar donde el linker encuentre ./lib, y la
    # configuración se declara aquí en vez de heredarse del desarrollador
    # (un 'target: interp' haría que --emit-hir además ejecutara).
    _enlaza_lib(destino)
    with open(os.path.join(destino, ".suriaX_config.yaml"), "w",
              encoding="utf-8") as fh:
        fh.write("version: 1\ntarget: native\n")
    fuente = os.path.join(destino, "referencia.srcx")
    with open(fuente, "w", encoding="utf-8") as fh:
        fh.write(_REFERENCIA)

    phir = os.path.join(destino, "referencia.phir")
    emit = subprocess.run(
        [sys.executable, _COMPILER, fuente, "--emit-hir", phir],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180, cwd=_REPO_ROOT,
    )
    if emit.returncode != 0 or not os.path.isfile(phir):
        raise AssertionError(
            "el programa de referencia no compiló:\n"
            f"{emit.stdout}\n{emit.stderr}")

    # las unidades referenciadas se resuelven RELATIVAS al .phir principal,
    # y el compilador ya las emite a su lado
    return phir


def _en_el_path() -> None:
    """Pone el repositorio y ``V0/`` donde Python los encuentre.

    Lo llaman TODOS los que importan del compilador, y no solo ``_cargar``:
    si solo lo hiciera uno, importar ``src.HIR.pretty`` funcionaría o no
    según qué prueba hubiera corrido antes.
    """
    for ruta in (_REPO_ROOT, _V0_ROOT):
        if ruta not in sys.path:
            sys.path.insert(0, ruta)


def _cargar(phir: str):
    """El ``Module`` leído por el lector de Python."""
    _en_el_path()
    from runtime.interpreter.loader import load_module
    return load_module(phir)


def _cpp(binario: str, phir: str, *opciones: str) -> subprocess.CompletedProcess:
    return subprocess.run([binario, phir, *opciones], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=120)


def _con_referencia(comprobar) -> None:
    """Compila el programa de referencia una vez y se lo pasa a ``comprobar``."""
    binario = _binario()
    if binario is None:
        omitir("build/bin/suriax-hir no está construido "
               "(cmake -S . -B build && cmake --build build --target suriax-hir)")
    # el temporal va DENTRO del repo porque el linker resuelve './lib' desde
    # ahí; el prefijo lo hace reconocible si una corrida se interrumpe.
    with tempfile.TemporaryDirectory(dir=_REPO_ROOT,
                                     prefix="suriax-cpp-") as tmp:
        comprobar(binario, _compilar(tmp), tmp)


def _vm(binario: str, phir: str):
    """Ejecuta el .phir en la VM del backend y devuelve lo que dio 'main'."""
    salida = _cpp(binario, phir, "--run")
    for linea in salida.stdout.splitlines():
        if linea.startswith("[vm] main() -> "):
            return int(linea.rsplit("-> ", 1)[1])
    return None


def _con_programa(fuente: str, comprobar) -> None:
    """Compila ``fuente`` a .phir y se lo pasa a ``comprobar`` con el binario."""
    binario = _binario()
    if binario is None:
        omitir("build/bin/suriax-hir no está construido "
               "(cmake -S . -B build && cmake --build build --target suriax-hir)")
    with tempfile.TemporaryDirectory(dir=_REPO_ROOT,
                                     prefix="suriax-vm-") as tmp:
        # el destino de los volcados se ancla a la RAÍZ DEL PROYECTO (el
        # directorio del yaml), así que el temporal declara la suya: sin
        # esto el .phir aterrizaba en el 'dumps/' del repositorio.
        with open(os.path.join(tmp, ".suriaX_config.yaml"), "w",
                  encoding="utf-8") as fh:
            fh.write("version: 1\ntarget: native\n")
        ruta = os.path.join(tmp, "prog.srcx")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(fuente)
        # ./lib junto al fuente: el linker ancla la búsqueda al directorio
        # del que importa, así que sin esto un programa con '#import' no
        # compila aquí. Un enlace y no una copia — son los archivos REALES
        # del repositorio los que se están probando.
        _enlaza_lib(tmp)
        phir = os.path.join(tmp, "prog.phir")
        proc = subprocess.run(
            [sys.executable, _COMPILER, ruta, "--emit-hir", phir],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", cwd=tmp, timeout=120)
        assert os.path.isfile(phir), (proc.stdout, proc.stderr)
        # las unidades de librería se resuelven RELATIVAS al .phir principal,
        # y el compilador ya las deja a su lado (antes iban a 'dumps/' y
        # había que copiarlas aquí)
        # el intérprete, como oráculo: su código de salida son los 8 bits
        # bajos de lo que devuelve 'main'
        corrida = subprocess.run([sys.executable, _COMPILER, ruta, "--run"],
                                 capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", cwd=tmp,
                                 timeout=120)
        comprobar(binario, phir, corrida)


def _codigo_de_proceso(valor: int) -> int:
    """Lo que ve el sistema operativo del código de salida de un proceso:
    POSIX conserva 8 bits; Windows, 32 (671 sigue siendo 671)."""
    return valor & 0xFFFFFFFF if os.name == "nt" else valor & 0xFF
