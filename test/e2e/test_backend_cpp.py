"""e2e/backend_cpp — prueba DIFERENCIAL: lector de HIR en C++ vs. el de Python.

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

Se salta (con aviso) si el binario no está construido o si falta protobuf:
el frontend no depende del backend nativo y su CI no puede quedar roja por
no haber corrido CMake.

    cmake -S . -B build && cmake --build build --target suriax-hir
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_V0_ROOT = os.path.join(_REPO_ROOT, "V0")
_COMPILER = os.path.join(_V0_ROOT, "main.py")

#: dónde deja CMake el CLI del lector (`RUNTIME_OUTPUT_DIRECTORY`).
_DEFAULT_BIN = os.path.join(_REPO_ROOT, "build", "bin", "suriax-hir")

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

    dt.int8 chico;
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
}

#extern cpp{
int ayuda_nativa() { return 1; }
}
"""


def _skip(reason: str) -> None:
    print(f"      (omitido: {reason})", file=sys.stderr)


def _binario() -> str | None:
    """El CLI del lector C++, o ``None`` si nadie lo ha construido."""
    ruta = os.environ.get("SURIAX_HIR_BIN", _DEFAULT_BIN)
    return ruta if os.path.isfile(ruta) and os.access(ruta, os.X_OK) else None


def _sin_protobuf() -> bool:
    try:
        import google.protobuf  # noqa: F401
    except ImportError:
        return True
    return False


def _compilar(destino: str) -> str:
    """Compila el programa de referencia dentro de ``destino`` y devuelve el
    ``.phir``, con sus unidades ``.libsrx`` al lado (viajan juntas)."""
    # El .srcx tiene que estar donde el linker encuentre ./lib, y la
    # configuración se declara aquí en vez de heredarse del desarrollador
    # (un 'target: interp' haría que --emit-hir además ejecutara).
    os.symlink(os.path.join(_REPO_ROOT, "lib"), os.path.join(destino, "lib"))
    with open(os.path.join(destino, ".suriaX_config.yaml"), "w",
              encoding="utf-8") as fh:
        fh.write("version: 1\ntarget: native\n")
    fuente = os.path.join(destino, "referencia.srcx")
    with open(fuente, "w", encoding="utf-8") as fh:
        fh.write(_REFERENCIA)

    phir = os.path.join(destino, "referencia.phir")
    emit = subprocess.run(
        [sys.executable, _COMPILER, fuente, "--emit-hir", phir],
        capture_output=True, text=True, timeout=180, cwd=_REPO_ROOT,
    )
    if emit.returncode != 0 or not os.path.isfile(phir):
        raise AssertionError(
            "el programa de referencia no compiló:\n"
            f"{emit.stdout}\n{emit.stderr}")

    # las unidades referenciadas se resuelven RELATIVAS al .phir principal
    dumps = os.path.join(destino, "dumps")
    if os.path.isdir(dumps):
        for archivo in os.listdir(dumps):
            if archivo.endswith(".phir"):
                shutil.copy(os.path.join(dumps, archivo),
                            os.path.join(destino, archivo))
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
                          text=True, timeout=120)


def _con_referencia(comprobar) -> None:
    """Compila el programa de referencia una vez y se lo pasa a ``comprobar``."""
    binario = _binario()
    if binario is None:
        _skip("build/bin/suriax-hir no está construido "
              "(cmake -S . -B build && cmake --build build --target suriax-hir)")
        return
    if _sin_protobuf():
        _skip("protobuf no disponible para emitir el HIR")
        return
    # el temporal va DENTRO del repo porque el linker resuelve './lib' desde
    # ahí; el prefijo lo hace reconocible si una corrida se interrumpe.
    with tempfile.TemporaryDirectory(dir=_REPO_ROOT,
                                     prefix="suriax-cpp-") as tmp:
        comprobar(binario, _compilar(tmp), tmp)


def test_la_vista_legible_es_identica_a_la_de_python():
    """La garantía central: el mismo .phir significa lo mismo para los dos."""
    def comprobar(binario, phir, _tmp):
        _en_el_path()
        from src.HIR.pretty import pretty
        esperada = pretty(_cargar(phir))
        obtenida = _cpp(binario, phir, "--pretty")
        assert obtenida.returncode == 0, obtenida.stderr
        if obtenida.stdout != esperada:
            esperadas = esperada.splitlines()
            obtenidas = obtenida.stdout.splitlines()
            for i, (want, got) in enumerate(zip(esperadas, obtenidas), 1):
                if want != got:
                    raise AssertionError(
                        "el lector C++ lee el HIR distinto que el de Python, "
                        f"línea {i}:\n  Python: {want!r}\n  C++   : {got!r}")
            raise AssertionError(
                "las dos vistas difieren en longitud "
                f"({len(esperadas)} vs {len(obtenidas)} líneas)")

    _con_referencia(comprobar)


def test_el_resumen_de_simbolos_es_identico_al_de_python():
    """La tabla de símbolos: lo otro que el lector tiene que reconstruir."""
    def comprobar(binario, phir, _tmp):
        _en_el_path()
        from runtime.interpreter.loader import summarize
        esperado = summarize(_cargar(phir)) + "\n"
        obtenido = _cpp(binario, phir, "--summary")
        assert obtenido.returncode == 0, obtenido.stderr
        assert obtenido.stdout == esperado, (
            "el resumen del lector C++ no coincide con el de Python:\n"
            f"--- Python ---\n{esperado}\n--- C++ ---\n{obtenido.stdout}")

    _con_referencia(comprobar)


def test_ningun_nodo_del_programa_de_referencia_queda_sin_handler():
    """El fail-fast del despacho: un nodo sin rama se ANOTA con su posición,
    nunca se salta. Es el equivalente C++ de ``_error_unsupported``."""
    def comprobar(binario, phir, _tmp):
        resultado = _cpp(binario, phir, "--verify")
        assert resultado.returncode == 0, (
            "el lector C++ no entendió algún nodo del programa de "
            f"referencia:\n{resultado.stderr}")

    _con_referencia(comprobar)


def test_liga_las_unidades_referenciadas():
    """El module linker: N unidades ligadas al cargar, transitivamente."""
    def comprobar(binario, phir, _tmp):
        resultado = _cpp(binario, phir, "--link")
        assert resultado.returncode == 0, resultado.stderr
        # el programa importa IO (paquete + stdp + stdpf) y d_types
        for alias in ("IO", "IO.stdp", "IO.stdpf", "d_types.dt_variables"):
            assert alias in resultado.stdout, (
                f"la unidad '{alias}' no se ligó:\n{resultado.stdout}")

    _con_referencia(comprobar)


def test_rechaza_una_schema_version_que_no_conoce():
    """Fail-fast de esquema: un .phir de otra versión no es 'casi correcto',
    es un artefacto cuyo significado cambió. Se rechaza ANTES de leer nada."""
    def comprobar(binario, phir, tmp):
        module = _cargar(phir)
        module.schema_version = 99
        futuro = os.path.join(tmp, "futuro.phir")
        with open(futuro, "wb") as fh:
            fh.write(module.SerializeToString(deterministic=True))

        resultado = _cpp(binario, futuro, "--summary")
        assert resultado.returncode != 0, (
            "el lector aceptó un HIR de una versión que no conoce")
        assert "99" in resultado.stderr and "schema_version" in resultado.stderr, (
            f"el rechazo no dice qué versión llegó:\n{resultado.stderr}")

    _con_referencia(comprobar)


def test_un_archivo_que_no_es_un_phir_no_revienta():
    """Bytes que no parsean: error con instrucción, no un crash."""
    def comprobar(binario, _phir, tmp):
        basura = os.path.join(tmp, "basura.phir")
        with open(basura, "wb") as fh:
            fh.write(b"\xff\xfe esto no es protobuf \x00\x01\x02")

        resultado = _cpp(binario, basura, "--summary")
        assert resultado.returncode != 0
        assert "Module HIR" in resultado.stderr, resultado.stderr

    _con_referencia(comprobar)


# --------------------------------------------------------------------------- #
# '#extern cpp': el viaje hasta el lado de C++
# --------------------------------------------------------------------------- #

def _compilador_cpp() -> str | None:
    """Un compilador de C++ del sistema, o ``None``."""
    for nombre in ("c++", "g++", "clang++"):
        ruta = shutil.which(nombre)
        if ruta is not None:
            return ruta
    return None


def test_los_bloques_extern_aterrizan_como_cpp_compilable():
    """El lexer lo captura crudo, la Semántica no lo mira y el HIR lo
    transporta intacto. Aquí se convierte en un archivo que un compilador de
    C++ acepta — que es lo único que demuestra que el viaje sirvió: si nunca
    se compiló el código generado, no se probó."""
    def comprobar(binario, phir, tmp):
        salida = os.path.join(tmp, "extern.cpp")
        resultado = _cpp(binario, phir, "--emit-cpp", salida)
        assert resultado.returncode == 0, resultado.stderr
        assert os.path.isfile(salida), resultado.stderr

        with open(salida, encoding="utf-8") as fh:
            texto = fh.read()
        assert "ayuda_nativa" in texto, texto
        assert "#line" in texto, "sin '#line' los errores no vuelven al .srcx"

        compilador = _compilador_cpp()
        if compilador is None:
            _skip("no hay compilador de C++ para verificar lo emitido")
            return
        compilado = subprocess.run([compilador, "-fsyntax-only", salida],
                                   capture_output=True, text=True, timeout=120)
        assert compilado.returncode == 0, (
            "lo que el backend emite no es C++ válido:\n" + compilado.stderr)

    _con_referencia(comprobar)


def test_un_error_en_el_cpp_apunta_al_srcx_del_usuario():
    """La razón de ser del ``#line``: quien escribe ``#extern cpp`` depura su
    propio archivo, no uno generado que nunca vio."""
    compilador = _compilador_cpp()
    if compilador is None:
        _skip("no hay compilador de C++")
        return

    def comprobar(binario, _phir, tmp):
        # un programa aparte, con C++ ROTO a propósito
        fuente = os.path.join(tmp, "roto.srcx")
        with open(fuente, "w", encoding="utf-8") as fh:
            fh.write("fn main() -> int { return 0; }\n"
                     "\n"
                     "#extern cpp{\n"
                     "int roto( { return 1; }\n"
                     "}\n")
        phir = os.path.join(tmp, "roto.phir")
        emit = subprocess.run(
            [sys.executable, _COMPILER, fuente, "--emit-hir", phir],
            capture_output=True, text=True, timeout=180, cwd=_REPO_ROOT)
        assert emit.returncode == 0 and os.path.isfile(phir), emit.stderr

        salida = os.path.join(tmp, "roto.cpp")
        assert _cpp(binario, phir, "--emit-cpp", salida).returncode == 0

        compilado = subprocess.run([compilador, "-fsyntax-only", salida],
                                   capture_output=True, text=True, timeout=120)
        assert compilado.returncode != 0, "el C++ roto tenía que fallar"
        # el error habla del .srcx y de la línea REAL del bloque (la 4)
        assert "roto.srcx:4" in compilado.stderr, compilado.stderr

    _con_referencia(comprobar)


def test_un_target_desconocido_se_rechaza_con_su_unidad():
    """Solo 'cpp' viaja a este backend. Un target que no conoce se rechaza en
    vez de escribirse en un archivo que luego no compila."""
    from V0.src.HIR.stubs import load_hir_pb2

    def comprobar(binario, phir, tmp):
        pb = load_hir_pb2()
        module = _cargar(phir)
        decl = module.items.add()
        decl.ln, decl.col = 1, 1
        decl.extern_block.target = "rust"
        decl.extern_block.raw = "fn nada() {}"
        raro = os.path.join(tmp, "raro.phir")
        with open(raro, "wb") as fh:
            fh.write(module.SerializeToString(deterministic=True))

        resultado = _cpp(binario, raro, "--emit-cpp",
                         os.path.join(tmp, "raro.cpp"))
        assert resultado.returncode != 0, "un target desconocido no debe pasar"
        assert "rust" in resultado.stderr, resultado.stderr

    _con_referencia(comprobar)


# --------------------------------------------------------------------------- #
# RESOLUCIÓN: el lector no solo recorre el árbol, lo entiende
# --------------------------------------------------------------------------- #
# '--pretty' demuestra que el lector visita cada nodo; '--resolve' demuestra
# que sabe QUÉ significa: a qué función llama cada llamada, qué slots tiene
# cada marco y qué destruye cada bloque. Son preguntas distintas — imprimir
# 'foo(2, 3)' no exige saber a qué 'foo' se llama— y es la segunda la que un
# MIR necesita respondida antes de poder bajar nada.

def test_el_lector_resuelve_el_programa_de_referencia_entero():
    """Cero llamadas sin resolver: si el backend no sabe a qué llama un sitio,
    no puede generar código para él y tiene que verse."""
    def comprobar(binario, phir, _tmp):
        resultado = _cpp(binario, phir, "--resolve")
        assert resultado.returncode == 0, (
            f"quedaron llamadas sin resolver:\n{resultado.stdout}"
            f"\n{resultado.stderr}")
        assert "0 llamada(s) sin resolver" in resultado.stdout
    _con_referencia(comprobar)


def test_cada_funcion_de_la_imagen_aparece_con_sus_slots():
    """Los slots (parámetros y locales en un solo espacio de índices) son lo
    primero que un MIR asigna; numerarlos aquí evita que cada backend invente
    su propia numeración."""
    def comprobar(binario, phir, _tmp):
        salida = _cpp(binario, phir, "--resolve").stdout
        assert "fn main" in salida
        assert "entrada: main" in salida
        # los prototipos del host se distinguen de las funciones con cuerpo
        assert "(prototipo: lo aporta el host)" in salida
        assert "slot 0  param" in salida
    _con_referencia(comprobar)


def test_las_destrucciones_del_bloque_llegan_ligadas_a_su_hook():
    """El frontend decidió DÓNDE muere cada valor; el backend comprueba que el
    destructor que nombra existe de verdad en la imagen."""
    def comprobar(binario, phir, _tmp):
        salida = _cpp(binario, phir, "--resolve").stdout
        assert "destruye " in salida, salida
        assert "NO LIGADO" not in salida, (
            "un drop nombra un hook que la imagen no tiene:\n" + salida)
    _con_referencia(comprobar)


def test_un_hook_de_un_primitivo_se_marca_nativo_y_no_como_agujero():
    """'len(s)' sobre un 'str' viaja como HookRef, pero ninguna unidad puede
    declararlo (SEM006 prohíbe colgarle hooks a un primitivo): lo implementa
    el backend. Confundirlo con 'no sé a qué llama esto' sería un falso
    agujero."""
    def comprobar(binario, phir, _tmp):
        salida = _cpp(binario, phir, "--resolve").stdout
        assert "-> nativo" in salida, salida
    _con_referencia(comprobar)


# --------------------------------------------------------------------------- #
# MIR + VM: el backend nativo empieza a EJECUTAR
# --------------------------------------------------------------------------- #
# '--resolve' demuestra que el backend entiende el HIR; esto demuestra que
# puede correrlo. La prueba no es que la VM devuelva "algo": es que devuelva
# LO MISMO que el intérprete, porque dos ejecutores que discrepan son dos
# lenguajes. Es el mismo diferencial que ya protege la vista legible.

_ARITMETICA = """\
fn abs(int x) -> int { if (x < 0) { return -x; }; return x; };

fn suma_hasta(int n) -> int {
    var int total = 0;
    var int i = 1;
    while (i <= n) { total = total + i; i = i + 1; };
    return total;
};

fn fib(int n) -> int {
    if (n < 2) { return n; };
    return fib(n - 1) + fib(n - 2);
};

fn en_rango(int x) -> bool { return x > 3 and x < 10; };

fn main() -> int {
    var int r = 0;
    if (en_rango(abs(-5))) { r = 1; };
    return abs(-5) + suma_hasta(10) + fib(15) + r;
};
"""


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
        _skip("build/bin/suriax-hir no está construido")
        return
    if _sin_protobuf():
        _skip("protobuf no disponible para emitir el HIR")
        return
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
        os.symlink(os.path.join(_REPO_ROOT, "lib"), os.path.join(tmp, "lib"))
        phir = os.path.join(tmp, "prog.phir")
        proc = subprocess.run(
            [sys.executable, _COMPILER, ruta, "--emit-hir", phir],
            capture_output=True, text=True, cwd=tmp, timeout=120)
        assert os.path.isfile(phir), (proc.stdout, proc.stderr)
        # las unidades de librería se resuelven RELATIVAS al .phir principal,
        # y el compilador las deja en 'dumps/': viajan al lado o el enlazado
        # del backend no las encuentra.
        dumps = os.path.join(tmp, "dumps")
        if os.path.isdir(dumps):
            for archivo in os.listdir(dumps):
                if archivo.endswith(".phir"):
                    shutil.copy(os.path.join(dumps, archivo),
                                os.path.join(tmp, archivo))
        # el intérprete, como oráculo: su código de salida son los 8 bits
        # bajos de lo que devuelve 'main'
        corrida = subprocess.run([sys.executable, _COMPILER, ruta, "--run"],
                                 capture_output=True, text=True, cwd=tmp,
                                 timeout=120)
        comprobar(binario, phir, corrida)


def test_la_vm_devuelve_lo_mismo_que_el_interprete():
    """El diferencial: aritmética, control de flujo, recursión y
    cortocircuito, ejecutados por los dos."""
    def comprobar(binario, phir, corrida):
        obtenido = _vm(binario, phir)
        assert obtenido is not None, "la VM no ejecutó"
        assert obtenido == 671, obtenido      # 5 + 55 + 610 + 1
        # el proceso del intérprete solo puede devolver 8 bits
        assert corrida.returncode == obtenido & 0xFF, (
            f"la VM dio {obtenido} y el intérprete salió con "
            f"{corrida.returncode}")
    _con_programa(_ARITMETICA, comprobar)


def test_el_cortocircuito_es_un_grafo_y_no_una_instruccion():
    """'a and b' no evalúa 'b' si no hace falta, y en el MIR eso se ve: hay
    una rama y dos caminos que se juntan. Es la razón de que el CFG sea
    explícito (ROADMAP Fase 6)."""
    def comprobar(binario, phir, _corrida):
        salida = _cpp(binario, phir, "--mir").stdout
        assert "branch" in salida, salida
        # el lado derecho vive en su propio bloque: si se evaluara siempre,
        # estaría en el mismo que la condición
        assert salida.count("bb") > 4, salida
    _con_programa(_ARITMETICA, comprobar)


def test_la_division_entera_trunca_igual_en_la_vm():
    """La semántica no puede diferir entre ejecutores: '-7 / 2' es -3 en los
    dos, y '(a/b)*b + a%b == a' se cumple en los dos."""
    def comprobar(binario, phir, corrida):
        obtenido = _vm(binario, phir)
        assert obtenido == 0, obtenido
        assert corrida.returncode == 0
    _con_programa("""\
fn main() -> int {
    var int fallos = 0;
    if (-7 / 2 != -3) { fallos = fallos + 1; };
    if (7 / -2 != -3) { fallos = fallos + 1; };
    if (-7 % 2 != -1) { fallos = fallos + 1; };
    if (-7 / 2 * 2 + -7 % 2 != -7) { fallos = fallos + 1; };
    return fallos;
};
""", comprobar)


def test_los_enteros_envuelven_a_64_bits_en_la_vm():
    """El 'int' del lenguaje es de 64 bits y envuelve. En C++ el
    desbordamiento con signo es comportamiento indefinido, así que la VM hace
    la cuenta en el tipo sin signo: sin eso el compilador podría optimizar
    asumiendo que no desborda y el resultado dejaría de coincidir."""
    def comprobar(binario, phir, corrida):
        assert _vm(binario, phir) == 0
        assert corrida.returncode == 0
    _con_programa("""\
fn main() -> int {
    var int max = 9223372036854775807;
    var int min = -9223372036854775808;
    var int fallos = 0;
    if (max + 1 != min) { fallos = fallos + 1; };
    if (min - 1 != max) { fallos = fallos + 1; };
    return fallos;
};
""", comprobar)


def test_lo_que_el_MIR_no_baja_se_dice_con_su_posicion():
    """Un MIR que ignorara en silencio lo que no sabe bajar ejecutaría otro
    programa. Se nombra la construcción y dónde está, y no se ejecuta.

    La construcción que falta hoy es ``&`` sobre un ESCALAR. El valor de un
    tipo con nombre ya vive en el montón —su handle ES su dirección—, pero el
    de un ``int`` está en un registro y no hay a qué apuntar; representarlo
    exige promover el local a una caja, y hoy el lenguaje no deja hacer casi
    nada con un ``ptr int`` (ni desreferenciarlo ni operarlo), así que se dice
    en vez de bajarse mal. El día que se baje, esta prueba tiene que cambiar
    de construcción — no borrarse: mientras quede algo sin cubrir, tiene que
    doler."""
    def comprobar(binario, phir, _corrida):
        resultado = _cpp(binario, phir, "--run")
        assert resultado.returncode != 0
        assert "no cubre" in resultado.stderr, resultado.stderr
        assert "escalar" in resultado.stderr, resultado.stderr
    _con_programa("""\
fn usa(int ptr p) -> void { };
fn main() -> int { var int x = 5; usa(&x); return x; };
""", comprobar)


# --------------------------------------------------------------------------- #
# el MIR COMPLETO: lo que la etapa tiene que cubrir para no quedarse desnuda
# --------------------------------------------------------------------------- #
# Cada prueba de aquí abajo es el mismo diferencial —el intérprete como
# oráculo— sobre una construcción que la aritmética no toca. La lista junta
# es el inventario de lo que el MIR sabe bajar; una construcción que no
# aparezca aquí es una que nadie está comprobando.

def _salida_del_programa(corrida) -> list:
    """Lo que imprimió el PROGRAMA, sin lo que dice el COMPILADOR.

    El compilador escribe en stdout lo que emite ('HIR ... generado', una
    línea por unidad de librería); comparar eso contra la salida de la VM
    —que solo ejecuta— haría fallar todo programa con un ``#import``.
    """
    def es_del_compilador(linea: str) -> bool:
        if linea.startswith(("frontend OK", "HIR ", "[exit]")):
            return True
        # '  unidad 'mem': 900 bytes -> /ruta/mem.phir'
        return linea.lstrip().startswith("unidad '") and " -> " in linea

    return [l for l in corrida.stdout.splitlines() if not es_del_compilador(l)]


def _diferencial(fuente: str, esperado: int) -> None:
    """El .phir corrido por los dos: mismo valor de vuelta y misma salida."""
    def comprobar(binario, phir, corrida):
        obtenido = _vm(binario, phir)
        assert obtenido == esperado, (obtenido, esperado)
        assert corrida.returncode == esperado & 0xFF, (
            f"la VM dio {obtenido} y el intérprete salió con "
            f"{corrida.returncode}")
        salida = _cpp(binario, phir, "--run").stdout.splitlines()
        salida = [l for l in salida if not l.startswith("[vm] main() -> ")]
        assert salida == _salida_del_programa(corrida), (
            salida, _salida_del_programa(corrida))
    _con_programa(fuente, comprobar)


def test_una_global_calculada_vale_lo_mismo_en_los_dos():
    """Registrar la global no basta: su inicializador es CÓDIGO y alguien
    tiene que ejecutarlo antes que 'main'. Sin eso valía cero."""
    _diferencial("""\
const int BASE = 7;
const int DOBLE = BASE * 2;
fn main() -> int { return BASE + DOBLE; };
""", 21)


def test_un_enum_es_un_entero_con_nombre():
    _diferencial("""\
enum E { A = 1, B = 10, C };
fn main() -> int {
    var E e = E.B;
    match (e) { case E.A: { return 0; }; case E.B: { return cast<int>(e) + cast<int>(E.C); }; };
    return 0;
};
""", 21)


def test_un_struct_viaja_como_handle_y_sus_campos_por_indice():
    """Los nombres de campo no llegan al MIR: el literal escribe en ORDEN DE
    DECLARACIÓN aunque se escriba desordenado, y el acceso lee por índice."""
    _diferencial("""\
struct { int v; } A;
struct { A dentro; int k; } B;
fn main() -> int {
    var B b = B{ k: 7, dentro: A{ v: 6 } };
    b.k = b.k - 1;
    return b.dentro.v * b.k;
};
""", 36)


def test_un_enum_con_payload_lleva_su_etiqueta_y_se_destructura():
    """Un enum SUMA no puede ser un entero: lleva valores dentro. Viaja como
    un objeto ``[etiqueta, campos...]``, el ``match`` compara la etiqueta y
    liga el payload en la rama. Que las variantes SIN payload del mismo enum
    también sean objetos no es desperdicio: el ``match`` lee siempre el campo
    0, y no puede depender de con cuál se construyó el valor."""
    _diferencial("""\
enum Dato { Vacio, Numero(int), Par(int, int) };
fn saca(Dato d) -> int {
    match (d) {
        case Dato.Vacio: { return 0; };
        case Dato.Numero(n): { return n; };
        case Dato.Par(a, b): { return a * b; };
    };
    return -1;
};
fn main() -> int {
    return saca(Dato.Numero(6)) + saca(Dato.Par(4, 5)) + saca(Dato.Vacio);
};
""", 26)


def test_un_puntero_a_un_valor_con_nombre_es_un_alias_de_verdad():
    """'&p' no copia: quien lo recibe escribe en el MISMO objeto. Es lo que
    hace el intérprete con sus celdas, y sin ello 'toca' no se vería."""
    _diferencial("""\
struct { int x; } P;
fn toca(P ptr mutable q) -> void { q.x = 99; };
fn main() -> int { var P p = P{ x: 1 }; toca(&p); return p.x; };
""", 99)


def test_las_cadenas_calculadas_existen_y_se_comparan_por_texto():
    """Una 'str' es el índice de su texto, y la tabla CRECE en ejecución:
    concatenar produce una cadena que no estaba en el fuente. Compararlas
    por índice habría dado falso para dos textos iguales."""
    _diferencial("""\
fn __write__(str s) -> void;
fn main() -> int {
    var str a = "ho";
    var str b = a + "la";
    __write__(f"{b} {len(b)} {b == \"hola\"}\\n");
    return len(b);
};
""", 4)


def test_los_hooks_del_vocabulario_fijo_se_llaman_como_funciones():
    _diferencial("""\
struct { int n; } C;
hook fn __len__(C ptr c) -> int { return c.n; };
hook fn __index__(C ptr c, int i) -> int { return c.n + i; };
hook fn __sizeof__(C ptr c) -> int { return 8; };
fn main() -> int { var C c = C{ n: 5 }; return len(c) + c[3] + sizeof(C); };
""", 21)


def test_el_destructor_corre_una_vez_por_valor_y_por_vuelta():
    """La lista de drops es estática pero el drop NO es incondicional: cada
    local destruible lleva una BANDERA de vivo, y el bucle la enciende en
    cada vuelta. Se comprueba por su efecto, que es lo único que prueba que
    corrió."""
    _diferencial("""\
struct { int id; } R;
fn __write__(str s) -> void;
hook fn __free__(R ptr r) -> void { __write__("drop\\n"); };
fn main() -> int {
    var int i = 0;
    while (i < 3) { var R a = R{ id: i }; i = i + 1; };
    return i;
};
""", 3)


def test_un_return_temprano_tambien_destruye():
    """Un bloque se cierra por 'return' igual que por caerse del final: en un
    CFG eso son dos aristas, y las dos tienen que pasar por el destructor.
    Uno que solo corriera al final sería una fuga."""
    _diferencial("""\
struct { int id; } R;
fn __write__(str s) -> void;
hook fn __free__(R ptr r) -> void { __write__("drop\\n"); };
fn main() -> int { var R a = R{ id: 3 }; if (a.id > 1) { return 1; }; return 0; };
""", 1)


def test_move_cede_el_destructor_y_por_eso_no_se_destruye_dos_veces():
    _diferencial("""\
struct { int id; } R;
fn __write__(str s) -> void;
hook fn __free__(R ptr r) -> void { __write__("drop\\n"); };
fn toma(R r) -> int { return r.id; };
fn main() -> int { var R a = R{ id: 4 }; return toma(move a); };
""", 4)


def test_un_throw_cruza_las_llamadas_y_lo_atrapa_la_rama_de_su_tipo():
    """El filtro del 'catch' es dinámico en el intérprete —pregunta de qué es
    el valor—; en el MIR el tipo lanzado viaja como una ETIQUETA, así que
    decidir la rama es comparar dos enteros. Tiene que dar lo mismo."""
    _diferencial("""\
fn falla() -> int { throw 9; return 0; };
fn medio() -> int { try { return falla(); } catch (str s) { return 1; }; return 0; };
fn main() -> int { try { return medio(); } catch (int n) { return 4; }; return 0; };
""", 4)


def test_una_excepcion_que_escapa_de_todo_sale_como_en_el_interprete():
    """No es un fallo de la VM: es el programa terminando mal, y los dos
    ejecutores tienen que decir lo mismo (código 70)."""
    def comprobar(binario, phir, corrida):
        assert corrida.returncode == 70, corrida.returncode
        resultado = _cpp(binario, phir, "--run")
        assert resultado.returncode == 70, (resultado.returncode,
                                            resultado.stderr)
        assert "no capturado" in resultado.stderr, resultado.stderr
    _con_programa("""\
fn main() -> int { throw 1; return 0; };
""", comprobar)


def test_el_indexado_crudo_de_un_bloque_no_es_el_de_una_cadena():
    """``buf[i]`` sobre un puntero es memoria; ``s[i]`` sobre una ``str`` es
    un carácter. Se escriben igual y no son lo mismo: bajar el primero como
    el segundo leería la tabla de constantes en vez del montón. El índice es
    un VALOR, así que tampoco puede ser el acceso a campo de un struct, cuyo
    índice se resuelve al compilar."""
    _diferencial("""\
#import mem
fn main() -> int {
    var int ptr mutable b = mem.reserve<int>(4);
    var int i = 0;
    while (i < 4) { b[i] = i * 10; i = i + 1; };
    return b[3] - b[1];
};
""", 20)


def test_el_vector_de_la_stdlib_corre_igual_en_la_vm():
    """El diferencial sobre la librería REAL, que es lo que ejercita a la vez
    los genéricos, los métodos ``@impl``, los hooks de índice, las primitivas
    de memoria del host y el crecimiento. Si la VM y el intérprete discrepan
    aquí, discrepan en todo lo que se construya encima."""
    _diferencial("""\
#import array.vector as vec
fn __write__(str s) -> void;
fn main() -> int {
    var vec.Vector<int> v = vec.dynamic<int>(1);
    var int i = 0;
    while (i < 10) { v.push(i * i); i = i + 1; };
    v[0] = 100;
    __write__(f"{v.cap()} {v.len()} {v[0]} {v.get(9)}\\n");
    return v.pop();
};
""", 81)


# --------------------------------------------------------------------------- #
# la VERIFICACIÓN de propiedad y préstamos sobre el CFG (ROADMAP Fase 6)
# --------------------------------------------------------------------------- #
# El frontend rechaza lo que se ve mirando una sentencia; esto responde lo que
# solo se puede responder mirando CAMINOS. Que encuentre algo que el frontend
# dejó pasar es la prueba de que la etapa hacía falta — y que NO encuentre
# nada en un programa correcto es la prueba de que se puede creer.

def test_la_verificacion_calla_ante_un_programa_correcto():
    """Sin esto el verificador no valdría nada: uno que avisara siempre
    tendría razón siempre y no diría nada."""
    def comprobar(binario, phir, _corrida):
        salida = _cpp(binario, phir, "--mir").stdout
        assert "0 problema(s) de propiedad" in salida, salida
    _con_programa("""\
struct { int id; } R;
fn __write__(str s) -> void;
hook fn __free__(R ptr r) -> void { __write__("drop\\n"); };
fn toma(R r) -> int { return r.id; };
fn main() -> int { var R a = R{ id: 1 }; return toma(move a); };
""", comprobar)


def test_un_move_dentro_de_un_bucle_se_ve_en_el_grafo_y_no_en_el_arbol():
    """La segunda vuelta lee lo que la primera transfirió. El frontend acepta
    el programa —sobre el árbol el 'move' y la lectura están en ramas
    distintas—; sobre el CFG la arista de retorno del bucle une los dos
    caminos y la respuesta cambia. Es exactamente por esto que la
    verificación de propiedad vive en el MIR y no antes."""
    def comprobar(binario, phir, _corrida):
        salida = _cpp(binario, phir, "--mir").stdout
        assert "1 problema(s) de propiedad" in salida, salida
        assert "ALGUN camino lo transfiriera" in salida, salida
    _con_programa("""\
struct { int id; } R;
fn __write__(str s) -> void;
hook fn __free__(R ptr r) -> void { __write__("drop\\n"); };
fn toma(R r) -> int { return r.id; };
fn main() -> int {
    var R a = R{ id: 1 };
    var int i = 0;
    var int t = 0;
    while (i < 2) { t = t + toma(move a); i = i + 1; };
    return t;
};
""", comprobar)


def test_un_prestamo_no_sobrevive_al_valor_que_presta():
    """Los tiempos de vida de un 'ptr', que es la otra mitad de lo que la
    Fase 6 pide en esta etapa: prestar y después transferir deja el puntero
    apuntando a un valor que ya no es de nadie."""
    def comprobar(binario, phir, _corrida):
        salida = _cpp(binario, phir, "--mir").stdout
        assert "puntero sigue apuntando" in salida, salida
    _con_programa("""\
struct { int id; } R;
fn __write__(str s) -> void;
hook fn __free__(R ptr r) -> void { __write__("drop\\n"); };
fn toma(R r) -> int { return r.id; };
fn lee(R ptr p) -> int { return p.id; };
fn main() -> int {
    var R a = R{ id: 1 };
    var R ptr p = &a;
    var int n = toma(move a);
    return lee(p);
};
""", comprobar)
