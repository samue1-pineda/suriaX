"""``#extern cpp`` EJECUTABLE: compilar el bloque y ligarlo a sus prototipos.

El bloque de C++ ya viajaba hasta el otro lado —el lector nativo lo escribe
como una unidad de traducción con ``#line`` (``suriax-hir --emit-cpp``)—, pero
ahí se quedaba: nadie lo compilaba y nada lo llamaba. Esto cierra el viaje.

El mecanismo NO es nuevo: es el de siempre en este proyecto, *prototipo +
intrínseco*. Un ``fn abre_ventana() -> void;`` sin cuerpo es un contrato que
alguien tiene que cumplir; ``intrinsics.py`` lo cumple con Python y aquí se
cumple con el C++ que el propio programa trae::

    #extern cpp{
    #include <iostream>
    extern "C" void saluda() { std::cout << "hola\\n"; }
    }

    fn saluda() -> void;           // el prototipo que lo invoca

    fn main() -> int { saluda(); return 0; }

Tres decisiones que conviene tener presentes:

* **``extern "C"`` es obligatorio** en el lado C++. El símbolo se busca por su
  NOMBRE, y el *mangling* de C++ lo cambia según la firma: sin ``extern "C"``
  el enlace fallaría por algo que no se ve en el código.
* **Solo se ligan los prototipos que el programa declara.** Una función C++
  que nadie declaró en suriaX no se toca: el contrato lo fija el lenguaje, no
  lo que exporte la biblioteca.
* **No se compila si nada cambió.** El ``.so`` se reconstruye solo cuando el
  ``.cpp`` generado es más nuevo, porque invocar al compilador de C++ en cada
  ejecución convertiría un programa de 20 ms en uno de dos segundos.

Esto es el puente del INTÉRPRETE. El backend nativo ligará los mismos
símbolos en su enlazado, sin ``ctypes`` de por medio; lo que tiene que
coincidir entre los dos es la tabla de tipos de abajo, no el mecanismo.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import struct
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

def _estandar_cpp() -> str:
    """El estándar de C++ ÚNICO del proyecto (``CXX_STANDARD`` de
    ``version.py``, la misma fuente que lee CMake). Un bloque ``#extern cpp``
    compilado en otro estándar que el backend que lo enlace es un conflicto
    que compila y falla después."""
    import sys
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if raiz not in sys.path:
        sys.path.insert(0, raiz)
    from version import CXX_STANDARD
    return CXX_STANDARD


#: Tipo del lenguaje -> tipo de ``ctypes`` en la frontera.
#:
#: ``int`` es de 64 bits por definición del lenguaje y ``char`` es UN code
#: point (no un byte), así que van a ``int64`` y ``uint32``. Esta tabla tiene
#: que decir lo mismo que la de ``htims/utils/cxx.py``, que genera el
#: prototipo C++ que el usuario implementa: son los dos lados del mismo
#: contrato. No se importa la una a la otra porque ``htims`` no puede depender
#: del runtime (ver ``htims/readme.md``, *Fronteras*); un test compara las dos.
_CTYPES: Dict[int, Any] = {}


def _tabla() -> Dict[int, Any]:
    """La tabla ``TypeKind -> ctypes``, construida al primer uso.

    Perezosa porque los ``TypeKind`` son los del esquema del HIR y ese módulo
    solo existe si protobuf está instalado — importarlo al cargar este
    archivo ataría el runtime a una dependencia que quizá no hace falta.
    """
    if _CTYPES:
        return _CTYPES
    # espejo de 'TypeKind' del .proto (valores estables)
    _CTYPES.update({
        1: None,                   # VOID
        2: ctypes.c_bool,          # BOOL
        3: ctypes.c_int64,         # INT
        4: ctypes.c_double,        # FLOAT
        5: ctypes.c_uint32,        # CHAR: un code point
        6: ctypes.c_char_p,        # STR: 'const char*' UTF-8 (ver marshalling)
        7: ctypes.c_void_p,        # POINTER
        12: ctypes.c_uint8,        # BYTE
    })
    return _CTYPES


#: un 'byte ptr': un buffer de 'uint8_t'. Se distingue de los demas punteros
#: porque el intérprete no sabe, mirando las celdas (enteros de Python), si
#: un bloque es de 'int' o de 'byte': lo dice el TIPO del parámetro.
_PTR_BYTE = ctypes.POINTER(ctypes.c_uint8)

#: ``TypeKind`` que NO se pueden pasar por esta frontera, con el porqué.
_SIN_ABI = {
    8: "un nullable: cómo viaja el nulo a C++ todavía no está fijado",
    9: "un tipo nominal: su layout en C++ lo decidirá el backend nativo",
    10: "un 'type' de primera clase",
    11: "un 'error T': el acarreo del error a C++ no está fijado",
}

#: Nombre de la biblioteca que se construye, dentro del directorio de dumps.
_MODULO = "extern_cpp"

#: Variable de entorno con banderas extra para el compilador de C++
#: (``SURIAX_CPP_FLAGS="-lX11 -lm"``). La vía normal es
#: ``toolchain.cxx_flags`` del yaml; esta existe porque las banderas de
#: enlazado son de la MÁQUINA, no del proyecto —la misma librería necesita
#: ``-lX11`` la use quien la use— y porque el yaml requiere ``pyyaml``, que
#: es opcional: sin él no habría forma de enlazar nada.
FLAGS_ENV = "SURIAX_CPP_FLAGS"


@dataclass
class Report:
    """Lo que pasó al intentar ligar. Nunca lanza: se informa y se decide."""

    #: prototipos ligados a un símbolo del ``.so``
    ligados: List[str] = field(default_factory=list)
    #: prototipos que el programa declara y que este puente no pudo ligar,
    #: con el motivo. No es un fallo por sí mismo: puede que los cumpla el
    #: host en Python.
    omitidos: List[Tuple[str, str]] = field(default_factory=list)
    #: por qué no se pudo construir nada (sin compilador, error de C++...)
    error: Optional[str] = None
    #: ruta de la biblioteca construida
    biblioteca: Optional[str] = None

    @property
    def hubo_bloques(self) -> bool:
        return self.biblioteca is not None or self.error is not None


def _compilador(config: Optional[dict], lenguaje: str) -> Optional[str]:
    """El compilador a usar para ``lenguaje`` (``"cpp"`` o ``"c"``).

    Orden: lo que el proyecto ESCRIBIÓ en su yaml
    (``toolchain.cxx_compiler`` / ``toolchain.c_compiler``), la variable de
    entorno de siempre (``CXX``/``CC``) y, si no, el que esté instalado.

    Un compilador escrito a mano se usa TAL CUAL y no se busca otro: si
    alguien apunta a un compilador concreto es porque los demás no le sirven,
    y caer en otro en silencio produciría un binario distinto del que pidió.

    Traer código de C++ exige un COMPILADOR, no un sistema de build: aquí no
    se genera un CMake ni un Makefile, se invoca lo que el usuario ya tiene.
    """
    toolchain = (config or {}).get("toolchain") or {}
    clave = "cxx_compiler" if lenguaje == "cpp" else "c_compiler"
    escrito = (toolchain.get(clave) or "").strip()
    if escrito:
        return escrito if (os.path.isabs(escrito) or shutil.which(escrito)) \
            else None
    variable = "CXX" if lenguaje == "cpp" else "CC"
    desde_entorno = os.environ.get(variable)
    if desde_entorno:
        return desde_entorno if shutil.which(desde_entorno) else None
    for nombre in (("g++", "clang++") if lenguaje == "cpp"
                   else ("gcc", "clang", "cc")):
        if shutil.which(nombre):
            return nombre
    return None


def _banderas(config: Optional[dict], lenguaje: str) -> List[str]:
    """Las banderas del usuario para ``lenguaje``, en un solo sitio.

    Tres fuentes y todas se SUMAN, porque responden a preguntas distintas:
    las rutas de cabeceras dicen dónde están los ``#include``, las banderas
    del yaml son las del proyecto y la variable de entorno es la de esta
    máquina o esta corrida.
    """
    toolchain = (config or {}).get("toolchain") or {}
    flags: List[str] = []
    for ruta in toolchain.get("include_c_paths") or []:
        flags.append(f"-I{ruta}")
    clave = "cxx_flags" if lenguaje == "cpp" else "c_flags"
    flags.extend(toolchain.get(clave) or [])
    # Un bloque de C++ que use una librería de C (OpenGL, X11...) necesita
    # sus banderas de enlazado igual: 'c_flags' se suma también al enlazar
    # C++, que es donde de verdad hacen falta.
    if lenguaje == "cpp":
        flags.extend(toolchain.get("c_flags") or [])
    flags.extend(os.environ.get(FLAGS_ENV, "").split())
    return flags


def _bloques(image) -> List[Tuple[str, str, int]]:
    """Los ``#extern cpp`` de TODA la imagen: ``(unidad, fuente, línea)``.

    También los de las librerías: una librería que trae C++ es C++ que el
    programa necesita, igual que sus funciones.
    """
    salida: List[Tuple[str, str, int]] = []
    unidades = [image.main] + [u for u in image.units.values()
                               if u is not image.main]
    for unidad in unidades:
        for item in unidad.module.items:
            if item.WhichOneof("node") != "extern_block":
                continue
            bloque = item.extern_block
            if bloque.target != "cpp":
                continue
            salida.append((unidad.module.source_file, bloque.raw, item.ln))
    return salida


def _requisitos(image) -> List[str]:
    """Las banderas que declaran los propios bloques (``requires(...)``).

    Se recogen de TODA la imagen y en orden de unidad, sin deduplicar más
    que lo repetido literal: quien trae el C++ es quien sabe de qué depende,
    y así el consumidor de una librería que usa X11 no tiene que enterarse
    de que existe X11.

    Van ANTES que las del proyecto en la línea de compilación por la misma
    razón por la que el yaml del usuario manda: si las dos dicen algo del
    mismo asunto, la última palabra la tiene quien compila.
    """
    salida: List[str] = []
    unidades = [image.main] + [u for u in image.units.values()
                               if u is not image.main]
    for unidad in unidades:
        for item in unidad.module.items:
            if item.WhichOneof("node") != "extern_block":
                continue
            if item.extern_block.target != "cpp":
                continue
            for flag in item.extern_block.requires:
                if flag not in salida:
                    salida.append(flag)
    return salida


def _prototipos(image) -> List[Any]:
    """Las funciones SIN cuerpo de la imagen: los contratos por cumplir."""
    salida: List[Any] = []
    unidades = [image.main] + [u for u in image.units.values()
                               if u is not image.main]
    for unidad in unidades:
        for item in unidad.module.items:
            if item.WhichOneof("node") != "function":
                continue
            fn = item.function
            if not fn.HasField("body"):
                salida.append((unidad, fn))
    return salida


def _tipo_ctypes(unidad, type_id: int) -> Tuple[Any, Optional[str]]:
    """``type_id`` -> tipo de ctypes, o ``(None, motivo)`` si no cruza."""
    tipos = unidad.module.types
    if type_id >= len(tipos):
        return None, "tipo desconocido"
    kind = tipos[type_id].kind
    motivo = _SIN_ABI.get(kind)
    if motivo is not None:
        return None, motivo
    if kind == 7 and tipos[type_id].inner.kind == 12:   # 'byte ptr'
        return _PTR_BYTE, None
    tabla = _tabla()
    if kind not in tabla:
        return None, f"tipo sin equivalente en C ({kind})"
    return tabla[kind], None


def _fuente(bloques: List[Tuple[str, str, int]], flags: List[str],
            compilador: Optional[str] = None) -> str:
    """La unidad de traducción, con ``#line`` al ``.srcx`` de cada bloque.

    Los ``#line`` no son cosmética: hacen que un error del compilador de C++
    apunte al archivo que el usuario escribió y no a este intermedio. Es la
    misma regla que aplica ``suriax-hir --emit-cpp``.
    """
    partes = [
        "// Generado por suriaX: los bloques '#extern cpp' del programa.",
        "// No se edita a mano — se regenera en cada compilacion.",
        "//",
        "// Los '#line' hacen que los errores del compilador de C++ apunten",
        "// al .srcx del usuario y no a este archivo.",
        "//",
        # Las banderas van AQUI, en el propio archivo generado, y no solo en
        # la orden de compilacion: son parte de como se construyo esto, asi
        # que un cambio de banderas cambia el archivo y la cache se invalida
        # sola. Sin esto, anadir '-lX11' no reconstruia nada y el '.so' viejo
        # fallaba al cargar por un simbolo que ya deberia estar.
        f"// compilador: {compilador or '(ninguno)'}",
        f"// banderas: {' '.join(flags) if flags else '(ninguna)'}",
        "",
    ]
    for archivo, raw, linea in bloques:
        partes.append(f'#line {linea} "{archivo}"')
        partes.append(raw if raw.endswith("\n") else raw + "\n")
    return "\n".join(partes)


def _objetivo(compilador: str) -> str:
    """Para qué máquina produce ``compilador`` (``-dumpmachine``), o "".

    Lo entienden g++ y clang++. Hace falta saberlo en Windows, donde hay dos
    ABI con reglas distintas para exportar un símbolo.
    """
    try:
        proceso = subprocess.run([compilador, "-dumpmachine"], capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proceso.stdout.strip() if proceso.returncode == 0 else ""


def _ajustes(objetivo: str, flags: List[str]) -> List[str]:
    """Las banderas que la MÁQUINA exige además de las del usuario.

    Una biblioteca de 32 bits no se carga en un proceso de 64: si el
    compilador produce por defecto para i686 (el clang de Windows lo hace) y
    quien la va a cargar es de 64 bits, se pide ``-m64``. Quien escribió
    ``-m32`` o ``-m64`` a mano ya decidió.
    """
    if any(f in ("-m32", "-m64") or f.startswith("--target") for f in flags):
        return []
    de_32 = objetivo.startswith(("i386", "i486", "i586", "i686"))
    return ["-m64"] if de_32 and sys.maxsize > 2 ** 32 else []


def definidos_coff(contenido: bytes) -> List[str]:
    """Los símbolos EXTERNOS que un objeto COFF (``.obj`` de Windows) define.

    Con la ABI de MSVC una DLL no exporta nada que no se marque
    (``__declspec(dllexport)``), y un ``extern "C"`` corriente no lo está: la
    biblioteca se construía y no traía ni un símbolo. Se exporta lo que el
    programa declara como prototipo y el objeto de verdad define; saber qué
    define exige leer su tabla de símbolos, que en COFF es simple:

    * cabecera normal (20 bytes) o ``/bigobj`` (56), y los símbolos de 18 o 20
      bytes a partir de ``PointerToSymbolTable``;
    * un símbolo está DEFINIDO si su sección es > 0, y es EXTERNO si su clase
      de almacenamiento es 2; su nombre va en línea (8 bytes) o en la tabla
      de cadenas que sigue a los símbolos;
    * en 32 bits el nombre de C lleva un ``_`` delante, que se quita.

    Es la misma lectura que hace ``backend/src/externo.cpp`` para la VM.
    """
    if len(contenido) < 20:
        return []
    firma1, firma2 = struct.unpack_from("<HH", contenido, 0)
    if firma1 == 0 and firma2 == 0xFFFF:          # /bigobj
        if len(contenido) < 56:
            return []
        maquina = struct.unpack_from("<H", contenido, 6)[0]
        tabla, cuantos = struct.unpack_from("<II", contenido, 48)
        tam, formato = 20, "<8sIiHBB"
    else:
        maquina = firma1
        tabla, cuantos = struct.unpack_from("<II", contenido, 8)
        tam, formato = 18, "<8sIhHBB"
    cadenas = tabla + cuantos * tam
    salida: List[str] = []
    i = 0
    while i < cuantos:
        base = tabla + i * tam
        if base + tam > len(contenido):
            break
        nombre, _valor, seccion, _tipo, clase, aux = struct.unpack_from(
            formato, contenido, base)
        if clase == 2 and seccion > 0:
            if nombre[:4] == b"\0\0\0\0":
                desde = cadenas + struct.unpack_from("<I", nombre, 4)[0]
                hasta = contenido.find(b"\0", desde)
                texto = contenido[desde:hasta if hasta >= 0 else len(contenido)]
            else:
                texto = nombre.rstrip(b"\0")
            simbolo = texto.decode("utf-8", "replace")
            if maquina == 0x14C and simbolo.startswith("_"):
                simbolo = simbolo[1:]
            salida.append(simbolo)
        i += 1 + aux
    return salida


def _construir(fuente: str, destino_dir: str, flags: List[str],
               compilador: Optional[str],
               nombres: Optional[List[str]] = None) -> Report:
    """Escribe el ``.cpp`` y lo compila a una biblioteca compartida.

    ``nombres`` son los prototipos del programa: con un toolchain de ABI de
    MSVC son lo que se exporta (ver :func:`definidos_coff`).
    """
    report = Report()
    if compilador is None:
        report.error = (
            "no hay compilador de C++ que usar: escribe uno en "
            "'toolchain.cxx_compiler' del .suriaX_config.yaml, exporta $CXX, "
            "o instala g++/clang++. El bloque '#extern cpp' viaja igual, "
            "pero sin compilador no se puede construir")
        return report

    os.makedirs(destino_dir, exist_ok=True)
    cpp = os.path.join(destino_dir, _MODULO + ".cpp")
    so = os.path.join(destino_dir, _MODULO + ".so")

    previo = None
    if os.path.isfile(cpp):
        with open(cpp, encoding="utf-8") as fh:
            previo = fh.read()
    if previo != fuente:
        with open(cpp, "w", encoding="utf-8") as fh:
            fh.write(fuente)
    elif os.path.isfile(so) and os.path.getmtime(so) >= os.path.getmtime(cpp):
        # nada cambio: invocar al compilador de C++ en cada ejecucion
        # convertiria un programa de milisegundos en uno de segundos.
        report.biblioteca = so
        return report

    # el MISMO estándar que el resto del proyecto (version.py): un bloque en
    # otro estándar que el backend que lo enlace es un conflicto esperando
    estandar = f"-std=c++{_estandar_cpp()}"
    objetivo = _objetivo(compilador)
    banderas = _ajustes(objetivo, flags) + list(flags)

    def correr(orden: List[str]) -> Optional[str]:
        try:
            # los mensajes del compilador de C++ pueden no venir en UTF-8
            # (MSVC escribe en la página de códigos de la consola): lo que no
            # se decodifica se reemplaza en vez de tumbar la compilación
            proceso = subprocess.run(orden, capture_output=True, text=True,
                                     encoding="utf-8", errors="replace", timeout=300)
        except (OSError, subprocess.SubprocessError) as exc:
            return f"no se pudo invocar a '{compilador}': {exc}"
        if proceso.returncode != 0:
            return "el bloque '#extern cpp' no compila:\n" + proceso.stderr.strip()
        return None

    if "msvc" in objetivo:
        # ABI de MSVC: primero el objeto, para saber que define, y despues la
        # DLL exportando justo eso ('/EXPORT' de un simbolo que no existe
        # rompe el enlazado, por eso no se exportan todos los prototipos)
        obj = os.path.join(destino_dir, _MODULO + ".obj")
        error = correr([compilador, "-c", estandar, "-O1", cpp, "-o", obj, *banderas])
        if error is None:
            with open(obj, "rb") as fh:
                definidos = set(definidos_coff(fh.read()))
            exportar = [f"-Wl,/EXPORT:{n}" for n in (nombres or []) if n in definidos]
            error = correr([compilador, "-shared", obj, "-o", so, *banderas, *exportar])
    else:
        # '-fPIC' es de ELF: en Windows (MinGW) el codigo ya es reubicable y
        # un clang de Windows lo rechaza
        pic = [] if os.name == "nt" else ["-fPIC"]
        error = correr([compilador, "-shared", *pic, estandar, "-O1", cpp, "-o", so,
                        *banderas])
    if error is not None:
        report.error = error
        return report
    report.biblioteca = so
    return report


#: Elemento de un bloque -> tipo de ctypes del buffer que cruza.
#: Solo los que tienen una representación de máquina evidente: un bloque de
#: structs o de cadenas no es un buffer, es un grafo de objetos.
_BUFFER: Dict[type, Any] = {int: ctypes.c_int64, float: ctypes.c_double}


def _a_buffer(bloque: Any) -> Tuple[Any, Any, Optional[str]]:
    """Un ``Block`` del intérprete -> un buffer contiguo de ctypes.

    Aquí está la diferencia entre "invocable" y COMBINABLE. La memoria del
    intérprete no son bytes: es una lista de celdas de Python, cada una con
    su estado (viva, movida, liberada) — que es lo que hace cumplir el
    modelo de propiedad. C++ no puede leer eso, así que se copia a un buffer
    de verdad, se pasa el puntero, y al volver se copia de vuelta si el
    puntero era mutable.

    Es COPIA DE ENTRADA Y SALIDA, no memoria compartida, y la diferencia se
    nota: C++ no ve los cambios que suriaX haga DURANTE la llamada (no puede
    haberlos, es de un solo hilo) y suriaX ve los de C++ solo al volver. El
    backend nativo pasará el puntero real —su memoria sí son bytes— y esta
    copia desaparecerá; el contrato que ve el usuario no cambia.
    """
    valores = []
    for celda in bloque.cells:
        valor = celda.value
        if valor is None:
            valor = 0
        valores.append(valor)
    tipos = {type(v) for v in valores if not isinstance(v, bool)}
    if not tipos:
        elemento = ctypes.c_int64
    elif len(tipos) > 1:
        return None, None, ("el bloque mezcla tipos y no es un buffer de "
                            "maquina")
    else:
        elemento = _BUFFER.get(tipos.pop())
        if elemento is None:
            return None, None, ("sus elementos no tienen representacion de "
                                "maquina (solo 'int', 'float' y 'byte' cruzan "
                                "como buffer)")
    arreglo = (elemento * len(valores))(*valores)
    return arreglo, elemento, None


def _envolver(fn_c: Any, params: List[Any], resultado: Any):
    """La función de ctypes, con el marshalling de la frontera.

    Dos marshallings, y los dos existen porque el intérprete no guarda sus
    valores como los guarda C:

    * ``str`` es texto Unicode aquí y ``const char*`` allí: se codifica a
      UTF-8 al entrar. La vuelta (un ``str`` de RETORNO) no se liga: quién
      libera ese buffer es una pregunta de propiedad sin contestar.
    * un PUNTERO a memoria reservada es una lista de celdas aquí y un bloque
      contiguo allí: se copia a un buffer, se pasa, y se copia de vuelta
      (ver :func:`_a_buffer`).
    """
    from .interpreter.errors import ExternBoundaryError
    from .interpreter.memory.block import Block

    def llamada(*args: Any) -> Any:
        preparados: List[Any] = []
        devolver: List[Tuple[Any, Any]] = []   # (buffer, bloque) por copiar
        for valor, tipo in zip(args, params):
            if tipo is ctypes.c_char_p and isinstance(valor, str):
                preparados.append(valor.encode("utf-8"))
            elif tipo is ctypes.c_uint32 and isinstance(valor, str):
                preparados.append(ord(valor))   # char -> code point
            elif tipo is _PTR_BYTE and isinstance(valor, Block):
                celdas = [c.value if c.value is not None else 0 for c in valor.cells]
                buffer = (ctypes.c_uint8 * len(celdas))(*[v & 0xFF for v in celdas])
                preparados.append(ctypes.cast(buffer, _PTR_BYTE))
                devolver.append((buffer, valor))
            elif tipo is ctypes.c_void_p and isinstance(valor, Block):
                buffer, _elemento, motivo = _a_buffer(valor)
                if motivo is not None:
                    raise ExternBoundaryError(
                        f"este bloque de memoria no puede cruzar a '#extern "
                        f"cpp': {motivo}")
                preparados.append(ctypes.cast(buffer, ctypes.c_void_p))
                devolver.append((buffer, valor))
            else:
                preparados.append(valor)
        salida = fn_c(*preparados)
        # De vuelta: lo que C++ escribio en el buffer vuelve a las celdas, y
        # por 'write' — no asignando '.value'—, porque escribir en una celda
        # es una operacion del modelo de memoria (comprueba el estado) y hay
        # una implementacion nativa donde '.value' es solo lectura.
        for buffer, bloque in devolver:
            for i, celda in enumerate(bloque.cells):
                celda.write(buffer[i])
        if resultado is ctypes.c_uint32:
            return chr(salida)
        return salida
    return llamada


def bind(image, *, dumps_dir: str, config: Optional[dict] = None) -> Report:
    """Compila los ``#extern cpp`` de ``image`` y liga sus prototipos.

    Devuelve el reporte; no lanza y no registra nada si no hay bloques. Los
    prototipos que no se puedan ligar quedan como estaban — puede que los
    cumpla el host en Python (``__write__`` lo hace), y decidir eso no es de
    este módulo.
    """
    from .interpreter import intrinsics

    bloques = _bloques(image)
    if not bloques:
        return Report()

    # 'toolchain' es donde el esquema del yaml pone lo que el backend C++
    # necesita para compilar y enlazar (ver how_to_run.md): las banderas de
    # este puente son eso mismo, no una seccion nueva.
    flags = _requisitos(image) + _banderas(config, "cpp")
    compilador = _compilador(config, "cpp")
    prototipos = _prototipos(image)
    report = _construir(_fuente(bloques, flags, compilador),
                        os.path.join(dumps_dir, "extern"), flags, compilador,
                        [fn.name for _unidad, fn in prototipos])
    if report.biblioteca is None:
        return report

    try:
        lib = ctypes.CDLL(report.biblioteca)
    except OSError as exc:
        report.error = f"no se pudo cargar '{report.biblioteca}': {exc}"
        return report

    for unidad, fn in prototipos:
        try:
            simbolo = getattr(lib, fn.name)
        except AttributeError:
            # el .so no lo exporta: puede ser un prototipo del host en Python
            # (asi se declara '__write__'), asi que no es un error de nadie.
            continue
        params: List[Any] = []
        motivo: Optional[str] = None
        for p in fn.params:
            tipo, fallo = _tipo_ctypes(unidad, p.type_id)
            if fallo is not None:
                motivo = f"el parametro '{p.name}' es {fallo}"
                break
            params.append(tipo)
        if motivo is None:
            resultado, fallo = _tipo_ctypes(unidad, fn.return_type_id)
            if fallo is not None:
                motivo = f"el retorno es {fallo}"
            elif resultado is ctypes.c_char_p:
                motivo = ("devuelve 'str': quien libera ese buffer es una "
                          "pregunta de propiedad todavia sin decidir")
            elif resultado is ctypes.c_void_p:
                # antes se ligaba y suriaX recibia la direccion como un entero:
                # un 'ptr' que no apunta a nada que el programa pueda usar
                motivo = ("devuelve un puntero de C++: de quien es esa memoria "
                          "todavia no esta decidido")
        if motivo is not None:
            report.omitidos.append((fn.name, motivo))
            continue
        simbolo.argtypes = params
        simbolo.restype = resultado
        intrinsics.register(fn.name, _envolver(simbolo, params, resultado))
        report.ligados.append(fn.name)
    return report


__all__ = ["Report", "bind"]
