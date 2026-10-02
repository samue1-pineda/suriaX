"""``#extern cpp`` EJECUTABLE: el bloque se compila y sus prototipos se ligan.

El viaje del bloque hasta una unidad de traducción ya lo cubre
``test_backend_cpp.py``; esto cubre el otro tramo — que ese C++ se construya y
que suriaX pueda LLAMARLO. Sin él, `#extern cpp` era código que cruzaba la
frontera y se quedaba mirando.

Todo aquí se OMITE si no hay compilador de C++: es una dependencia del
sistema, no del compilador, y un `.srcx` sin `#extern` sigue compilando sin
ella.
"""

import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import omitir, run_project  # noqa: E402
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_COMPILER = os.path.join(_REPO, "V0", "main.py")


def _hay_cxx() -> bool:
    return bool(os.environ.get("CXX") or shutil.which("g++")
                or shutil.which("clang++"))


def _correr(fuente: str, *, flags: str = "", stdin: str = "") -> str:
    """Compila y ejecuta ``fuente``; devuelve stdout+stderr."""
    entorno = dict(os.environ)
    # sin buffer: C++ y Python escriben al MISMO descriptor con buffers
    # distintos, y con el de Python en bloques la salida sale desordenada.
    entorno["PYTHONUNBUFFERED"] = "1"
    if flags:
        entorno["SURIAX_CPP_FLAGS"] = flags
    with tempfile.TemporaryDirectory(prefix="suriax-extern-") as tmp:
        ruta = os.path.join(tmp, "prog.srcx")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(fuente)
        proc = subprocess.run(
            [sys.executable, _COMPILER, ruta, "--run"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", cwd=tmp, timeout=300,
            input=stdin, env=entorno)
    return proc.stdout + proc.stderr


_CONSOLA = '''\
#extern cpp{
#include <iostream>

extern "C" void escribe(const char* texto) {
    std::cout << "[cpp] " << texto << std::endl;
}

extern "C" long long duplica(long long n) {
    return n * 2;
}
}

fn __write__(str s) -> void;
fn escribe(str texto) -> void;
fn duplica(int n) -> int;

fn main() -> int {
    escribe("hola");
    __write__(f"suriaX recibio {duplica(21)}\\n");
    return 0;
};
'''


def test_el_bloque_se_compila_y_sus_prototipos_se_ligan():
    if not _hay_cxx():
        omitir("no hay compilador de C++ (g++/clang++)")
    salida = _correr(_CONSOLA)
    assert "[cpp] hola" in salida, salida
    assert "suriaX recibio 42" in salida, salida


def test_una_cadena_cruza_la_frontera_como_const_char():
    """El único marshalling de la frontera: en suriaX es texto Unicode y en C
    un ``const char*``, así que se codifica a UTF-8 al entrar."""
    if not _hay_cxx():
        omitir("no hay compilador de C++ (g++/clang++)")
    salida = _correr(_CONSOLA.replace('escribe("hola")', 'escribe("añ日")'))
    assert "[cpp] añ日" in salida, salida


def test_sin_extern_c_el_simbolo_no_se_liga_y_el_error_lo_dice():
    """El símbolo se busca por su NOMBRE y el 'mangling' de C++ lo cambia
    según la firma: sin 'extern "C"' el enlace falla por algo que no se ve en
    el código, así que el diagnóstico tiene que nombrarlo."""
    if not _hay_cxx():
        omitir("no hay compilador de C++ (g++/clang++)")
    salida = _correr('''\
#extern cpp{
void solitaria() { }
}

fn solitaria() -> void;

fn main() -> int { solitaria(); return 0; };
''')
    # el prototipo queda sin cumplir y el interprete lo dice con su nombre
    assert "solitaria" in salida and "RT008" in salida, salida


def test_un_tipo_sin_abi_se_omite_diciendo_por_que():
    """Un prototipo que no puede cruzar no se liga a medias: se dice cuál y
    por qué, y el intérprete sigue pudiendo cumplirlo por otra vía."""
    if not _hay_cxx():
        omitir("no hay compilador de C++ (g++/clang++)")
    salida = _correr('''\
#extern cpp{
#include <cstring>
extern "C" const char* devuelve() { return "x"; }
}

fn devuelve() -> str;

fn main() -> int { return 0; };
''')
    assert "devuelve" in salida and "propiedad" in salida, salida


#: una LIBRERÍA que trae C++ y declara lo que necesita para compilarlo.
#: El '#error' es lo que hace la prueba concluyente: sin la bandera el
#: bloque no compila, así que pasar no puede ser casualidad.
_LIB_CON_REQUIRES = (
    '#extern cpp requires("-DFACTOR=7") {\n'
    '#ifndef FACTOR\n'
    '#error "la bandera que declaro la libreria no llego al compilador"\n'
    '#endif\n'
    'extern "C" long long escala(long long x) { return x * FACTOR; }\n'
    '}\n'
    'private fn escala(int x) -> int;\n'
    'public fn por_factor(int x) -> int { return escala(x); }\n'
    '#export as fac\n'
)

_MAIN_FAC = "#import fac\nfn main() -> int { return fac.por_factor(6); };\n"


def test_una_libreria_declara_las_banderas_que_su_cpp_necesita():
    """``requires("-DFACTOR=7")``: quien trae el C++ dice de qué depende.

    Antes las banderas salían SOLO del yaml del consumidor, así que usar una
    librería que enlaza X11 obligaba a enterarse de que existe X11 y a
    repetirlo en cada proyecto. Aquí el consumidor no declara toolchain
    ninguno y aun así compila.
    """
    if not _hay_cxx():
        return
    code, _out, err = run_project(
        {"lib/fac.libsrx": _LIB_CON_REQUIRES, "main.srcx": _MAIN_FAC},
        args=["--run"])
    assert code == 42, (code, err)      # 6 * 7, o sea que FACTOR llegó


def test_sin_declararlas_el_cpp_de_la_libreria_no_compila():
    """El control: si el ``requires`` no hiciera nada, la prueba de arriba
    pasaría igual y no probaría nada."""
    if not _hay_cxx():
        return
    sin = _LIB_CON_REQUIRES.replace(' requires("-DFACTOR=7")', "")
    code, _out, err = run_project(
        {"lib/fac.libsrx": sin, "main.srcx": _MAIN_FAC}, args=["--run"])
    assert code != 42, (code, err)
    assert "no llego al compilador" in err or "no compila" in err, err


def test_las_banderas_cambian_la_construccion_y_no_se_cachea_de_mas():
    """Las banderas son parte de CÓMO se construyó: si no entraran en la
    clave de caché, añadir '-l...' no reconstruiría nada y la biblioteca
    vieja fallaría al cargar por un símbolo que ya debería estar."""
    if not _hay_cxx():
        omitir("no hay compilador de C++ (g++/clang++)")
    from runtime import extern_cpp
    sin_flags = extern_cpp._fuente([("a.srcx", "int x = 1;\n", 1)], [])
    con_flags = extern_cpp._fuente([("a.srcx", "int x = 1;\n", 1)], ["-lm"])
    assert sin_flags != con_flags
    assert "-lm" in con_flags


def test_la_tabla_de_tipos_dice_lo_mismo_que_la_de_htims():
    """Son los dos lados del mismo contrato: 'htims/utils/cxx.py' genera el
    prototipo C++ que el usuario implementa y este módulo lo llama. No se
    importan entre sí (htims no puede depender del runtime), así que la
    frontera la paga esta prueba."""
    import ctypes

    from htims.utils import cxx as htims_cxx
    from runtime import extern_cpp

    esperado = {
        "int": ctypes.c_int64,
        "float": ctypes.c_double,
        "bool": ctypes.c_bool,
        "char": ctypes.c_uint32,
        "void": None,
    }
    # TypeKind del esquema: VOID=1, BOOL=2, INT=3, FLOAT=4, CHAR=5
    kinds = {"void": 1, "bool": 2, "int": 3, "float": 4, "char": 5}
    tabla = extern_cpp._tabla()
    for nombre, ctipo in esperado.items():
        assert tabla[kinds[nombre]] is ctipo, nombre
        rendido, motivo = htims_cxx.cxx_type(nombre)
        assert motivo is None, (nombre, motivo)
    # los anchos tienen que coincidir con lo que htims declara en C++
    assert htims_cxx.cxx_type("int")[0] == "int64_t"
    assert htims_cxx.cxx_type("char")[0] == "char32_t"
    assert htims_cxx.cxx_type("float")[0] == "double"


# --------------------------------------------------------------------------- #
# ¿COMBINABLE, o solo invocable?
# --------------------------------------------------------------------------- #
# El README promete "c++ interoperability". Llamar a una función no es
# interoperar: interoperar es que los DATOS crucen en los dos sentidos. Estas
# pruebas son esa demostración, y también dicen dónde se acaba — un límite
# conocido vale más que una promesa sin medir.

_MEMORIA = '''\
#import mem

#extern cpp{
extern "C" void llena(long long* datos, long long n) {
    for (long long i = 0; i < n; ++i) datos[i] = i * i;
}
extern "C" long long suma(const long long* datos, long long n) {
    long long total = 0;
    for (long long i = 0; i < n; ++i) total += datos[i];
    return total;
}
}

fn __write__(str s) -> void;
fn llena(int ptr mutable datos, int n) -> void;
fn suma(int ptr datos, int n) -> int;

fn main() -> int {
    var int ptr mutable datos = mem.reserve<int>(5);
    llena(datos, 5);
    __write__(f"cpp escribio {datos[0]} {datos[1]} {datos[2]} {datos[3]} {datos[4]}\\n");
    datos[0] = 100;
    __write__(f"suma {suma(datos, 5)}\\n");
    return 0;
};
'''


def test_la_memoria_de_suriax_cruza_a_cpp_y_vuelve():
    """La prueba de que es COMBINABLE y no solo invocable.

    suriaX reserva, C++ escribe, suriaX lee, suriaX modifica y C++ vuelve a
    leer. Los datos cruzan en los dos sentidos sobre el mismo bloque.
    """
    if not _hay_cxx():
        omitir("no hay compilador de C++ (g++/clang++)")
    salida = _correr(_MEMORIA)
    assert "cpp escribio 0 1 4 9 16" in salida, salida
    # 100 + 1 + 4 + 9 + 16: C++ ve el cambio que hizo suriaX
    assert "suma 130" in salida, salida


def test_un_bloque_sin_representacion_de_maquina_lo_dice():
    """Y aquí se acaba. La memoria del intérprete son CELDAS con estado (es
    lo que hace cumplir el modelo de propiedad), no bytes: un bloque de
    'str' es una lista de objetos y no un buffer. Se dice con su porqué en
    vez de reventar con un volcado de pila."""
    if not _hay_cxx():
        omitir("no hay compilador de C++ (g++/clang++)")
    salida = _correr('''\
#import mem
#extern cpp{
extern "C" void toca(void* p) { (void)p; }
}
fn __write__(str s) -> void;
fn toca(str ptr mutable p) -> void;
fn main() -> int {
    var str ptr mutable s = mem.reserve<str>(2);
    s[0] = "a"; s[1] = "b";
    toca(s);
    return 0;
};
''')
    assert "RT018" in salida, salida
    assert "representacion de maquina" in salida, salida


def test_el_compilador_y_las_banderas_salen_del_yaml():
    """Traer C++ no puede exigir un sistema de build: se detecta el
    compilador que el usuario ya tiene, y lo que necesite enlazar se escribe
    en el yaml del proyecto (no en una variable de entorno que se olvida)."""
    from runtime import extern_cpp

    config = {"toolchain": {
        "cxx_compiler": "clang++",
        "include_c_paths": [os.path.join("terceros", "inc")],
        "cxx_flags": ["-Wall"],
        "c_flags": ["-lGL"],
    }}
    assert extern_cpp._compilador(config, "cpp") == "clang++"
    banderas = extern_cpp._banderas(config, "cpp")
    assert "-I" + os.path.join("terceros", "inc") in banderas
    assert "-Wall" in banderas
    # una libreria de C la usa igual un bloque de C++ (OpenGL, X11...)
    assert "-lGL" in banderas


def test_sin_nada_escrito_se_detecta_el_compilador_del_sistema():
    from runtime import extern_cpp
    if not _hay_cxx():
        omitir("no hay compilador de C++ (g++/clang++)")
    assert extern_cpp._compilador({}, "cpp") is not None
    assert extern_cpp._compilador({"toolchain": {}}, "cpp") is not None


def test_un_compilador_escrito_que_no_existe_no_cae_en_otro():
    """Si alguien apunta a un compilador concreto es porque los demás no le
    sirven: caer en otro en silencio produciría un binario distinto del que
    pidió."""
    from runtime import extern_cpp
    config = {"toolchain": {"cxx_compiler": "no-existe-este-compilador"}}
    assert extern_cpp._compilador(config, "cpp") is None
