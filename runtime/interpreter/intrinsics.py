"""Interfaz del host: intrínsecos ``nombre -> callable`` (secc. 3).

Un PROTOTIPO del lenguaje (``fn suriax_write(str s) -> void;``) viaja en el
HIR sin cuerpo; ejecutarlo requiere que el host registre aquí su primitiva.
Es la costura de desacople: el backend C++ liga el mismo símbolo a su
``#extern``, el intérprete lo liga a Python — cero ``#extern`` requerido
para imprimir bajo ``target: interp``.

Registrar un intrínseco nuevo = una entrada en :data:`REGISTRY` (o
:func:`register` en tiempo de embed). Sin tocar evaluator ni loader.
"""

from __future__ import annotations

import math
import os
import re
import struct
import sys
from typing import Any, Callable, Dict, List

from .errors import (ConversionError, FileAccessError, IndexOutOfRangeError,
                     InvalidCastRuntimeError, NotIndexableError)
from .memory.block import Block
from .values import copy_on_bind


def _suriax_write(s: Any) -> None:
    sys.stdout.write(str(s))


def _suriax_reserve(size: Any) -> Block:
    """``__reserve__(int n)`` -> bloque de ``n`` celdas contiguas (``null``).

    Es la reserva CRUDA que una librería de vector (``lib/mem``) usa como
    almacén; la indexación ``buf[i]`` del evaluator recorre estas celdas.
    """
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise IndexOutOfRangeError(
            f"__reserve__ requiere un tamaño entero >= 0 (recibió {size!r})")
    return Block(size)


def _suriax_copy(dst: Any, src: Any, n: Any) -> None:
    """``__copy__(dst, src, n)`` -> copia ``n`` elementos de ``src`` a ``dst``.

    Ambos son bloques de ``__reserve__``; copia por VALOR celda a celda (lo
    que necesita el crecimiento de un vector: reservar mayor, copiar, liberar
    el viejo). Verifica límites en ambos extremos.
    """
    if not isinstance(dst, Block) or not isinstance(src, Block):
        raise NotIndexableError(
            "__copy__ opera sobre bloques de __reserve__ (dst y src)")
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        raise IndexOutOfRangeError(
            f"__copy__ requiere un conteo entero >= 0 (recibió {n!r})")
    if n > len(src) or n > len(dst):
        raise IndexOutOfRangeError(
            f"__copy__ de {n} elementos excede el tamaño de origen "
            f"({len(src)}) o destino ({len(dst)})")
    # POR VALOR: un struct se copia (con sus bloques), como en la VM. Antes
    # los dos bloques compartian el mismo objeto, y soltar el viejo —que
    # destruye lo que tiene— se llevaba los datos del nuevo.
    for i in range(n):
        dst.cells[i].write(copy_on_bind(src.cells[i].read()))


def _suriax_take(block: Any, i: Any) -> Any:
    """``__take__(bloque, i)`` -> SACA el valor de la celda ``i``.

    La celda queda MOVIDA (vacía): el valor tiene un dueño nuevo —quien lo
    recibe— y el bloque ya no lo destruye al soltarse. Leerla otra vez es
    RT001; escribirla la revive. Es lo que necesita ``pop`` de un vector de
    valores con destructor: devolver una COPIA dejaría dos dueños.
    """
    if not isinstance(block, Block):
        raise NotIndexableError(
            f"__take__ opera sobre un bloque de __reserve__ (recibió {block!r})")
    return block.element(i).move_out()


def _suriax_move(dst: Any, src: Any, n: Any) -> None:
    """``__move__(dst, src, n)`` -> MUEVE ``n`` celdas de ``src`` a ``dst``.

    Como ``__copy__``, pero las celdas de origen quedan vacías: cada valor
    tiene un solo dueño, ahora el bloque nuevo. Es como crece un vector de
    valores con destructor: reservar mayor, mover y soltar el viejo (que ya
    no tiene nada que destruir).
    """
    if not isinstance(dst, Block) or not isinstance(src, Block):
        raise NotIndexableError(
            "__move__ opera sobre bloques de __reserve__ (dst y src)")
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        raise IndexOutOfRangeError(
            f"__move__ requiere un conteo entero >= 0 (recibió {n!r})")
    if n > len(src) or n > len(dst):
        raise IndexOutOfRangeError(
            f"__move__ de {n} elementos excede el tamaño de origen "
            f"({len(src)}) o destino ({len(dst)})")
    for i in range(n):
        dst.cells[i].write(src.cells[i].move_out())


def _suriax_release(block: Any) -> None:
    """``__release__(bloque)`` -> el bloque deja de ser válido.

    No devuelve memoria al sistema —de eso se encarga el recolector de
    Python, y en el backend nativo lo hará el asignador de verdad—: lo que
    hace es marcar cada celda como LIBERADA, que es el invariante que le
    importa al lenguaje. Así un acceso posterior falla con el
    ``UseAfterFreeError`` que ya existe, en vez de leer un bloque que su
    dueño creía haber soltado.

    Es lo que permite que un contenedor CREZCA sin fugar: reservar mayor,
    copiar y soltar el viejo (ver ``lib/mem/main.libsrx``).
    """
    if not isinstance(block, Block):
        raise NotIndexableError(
            "__release__ opera sobre un bloque de __reserve__ "
            f"(recibió {block!r})")
    for cell in block.cells:
        cell.free()


# --------------------------------------------------------------------------- #
# tipos de ancho fijo (lib/d_types): conversiones NATIVAS
# --------------------------------------------------------------------------- #
#
# 'int8' y compañía no son primitivos del lenguaje: son tipos nominales que
# publica una librería. Su ANCHO, en cambio, no se puede escribir en suriaX
# —haría falta aritmética de bits sobre un entero que ya es de 64— así que la
# librería declara la conversión como PROTOTIPO y el host pone el cuerpo:
#
#     hook fn __cast__(int n) -> int8;      // dt_variables.libsrx
#
# Es el mismo patrón de '__write__' y '__reserve__', y es lo que hace que el
# tipo sea REAL en vez de una etiqueta con un '__sizeof__' al lado: antes
# 'cast<int8>(300)' no existía y el valor seguía siendo un entero de Python
# sin ancho ninguno.


def _entero_de(bits: int) -> Callable[[Any], int]:
    """Conversión a un entero CON SIGNO de ``bits``, truncando como C.

    Complemento a dos: se queda con los bits bajos y reinterpreta el rango
    alto como negativo (``cast<int8>(300)`` -> 44, ``cast<int8>(128)`` ->
    -128). Es lo que hará la VM/JIT sobre el registro real, así que el
    intérprete sigue sirviendo de oráculo para el differential testing en vez
    de divergir del target nativo.
    """
    modulo = 1 << bits
    mitad = modulo >> 1

    def convertir(valor: Any) -> int:
        # 'bool' es subclase de 'int' en Python: se excluye a mano para que
        # 'true' no se cuele como 1 por una conversión que nadie declaró.
        if not isinstance(valor, int) or isinstance(valor, bool):
            raise InvalidCastRuntimeError(
                f"conversión a un entero de {bits} bits requiere un 'int' "
                f"(recibió {valor!r})")
        bajos = valor & (modulo - 1)
        return bajos - modulo if bajos >= mitad else bajos

    return convertir


def _flotante_de(formato: str, bits: int) -> Callable[[Any], float]:
    """Conversión a un flotante IEEE-754 de ``bits``, redondeando de verdad.

    Se apoya en ``struct`` (stdlib, sin dependencias): empaquetar y
    desempaquetar en el ancho destino aplica exactamente el redondeo del
    formato — 'binary16' ('e'), 'binary32' ('f') y 'binary64' ('d').

    ``struct`` lanza ``OverflowError`` cuando el valor no cabe, pero IEEE-754
    dice que un desbordamiento redondea a infinito; se traduce aquí para no
    inventar una semántica propia.
    """
    def convertir(valor: Any) -> float:
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            raise InvalidCastRuntimeError(
                f"conversión a un flotante de {bits} bits requiere un número "
                f"(recibió {valor!r})")
        try:
            return struct.unpack(formato, struct.pack(formato, float(valor)))[0]
        except OverflowError:
            return math.inf if valor > 0 else -math.inf

    return convertir


#: ``nombre del tipo destino -> conversión``. La clave es el nombre NOMINAL
#: con el que la librería declaró el tipo, igual que el resto de los índices
#: del runtime (hooks y dunders se indexan por el nombre del receptor).
CASTS: Dict[str, Callable[[Any], Any]] = {
    "int8": _entero_de(8),
    "int16": _entero_de(16),
    "int32": _entero_de(32),
    "float16": _flotante_de("e", 16),
    "float32": _flotante_de("f", 32),
    "float64": _flotante_de("d", 64),
}

#: Ancho en BYTES de cada tipo de arriba, derivado del propio formato en vez
#: de repetirlo a mano. Es lo que debe coincidir con el '__sizeof__' que
#: declara la librería: si divergen, el tipo miente sobre su tamaño.
ANCHOS: Dict[str, int] = {
    "int8": 1, "int16": 2, "int32": 4,
    "float16": struct.calcsize("e"),
    "float32": struct.calcsize("f"),
    "float64": struct.calcsize("d"),
}


def lookup_cast(destino: str) -> Callable[[Any], Any] | None:
    """Conversión nativa hacia el tipo nominal ``destino``, si el host la trae.

    Se indexa por el nombre SIMPLE del tipo, no por el calificado con su
    unidad (``dt_variables.int8`` -> ``int8``). La identidad calificada es
    del compilador: sirve para que dos tipos homónimos de librerías distintas
    no compartan hooks. El host, en cambio, no aporta "la conversión del
    int8 de esa librería", aporta "la conversión a un entero de 8 bits" —
    una propiedad del ancho, que es lo que el nombre nombra. Atarla a una
    unidad concreta obligaría a cablear aquí el nombre de la librería que
    hoy lo declara.
    """
    return CASTS.get(destino.rsplit(".", 1)[-1])


# --------------------------------------------------------------------------- #
# llamadas al HOST: archivos, argumentos y salida (lib/sistema.libsrx)
# --------------------------------------------------------------------------- #
#
# No son syscalls: son servicios del host con el MISMO contrato en el
# intérprete y en la VM ('backend/src/vm.cpp', 'llamada_host'). Un programa
# no puede notar en qué motor corre, así que:
#   - los mensajes de error son canónicos (ver FileAccessError);
#   - los archivos se leen y escriben como UTF-8 SIN traducir los fines de
#     línea (newline=""): '\r\n' llega como '\r\n' en los dos motores;
#   - una carpeta se lista ORDENADA por nombre: el orden del sistema de
#     archivos no está definido y cambia entre máquinas.

#: los argumentos del programa: [archivo que se ejecuta, *los de después de --]
_ARGUMENTOS: List[str] = []
#: la última carpeta listada, para no releerla en cada '__entrada__'
_LISTADO: Dict[str, List[str]] = {}


def fijar_argumentos(argumentos: List[str]) -> None:
    """Los argumentos que verá el programa (los pone el CLI)."""
    _ARGUMENTOS[:] = [str(a) for a in argumentos]


def _leer_archivo(ruta: Any) -> str:
    ruta = str(ruta)
    if os.path.isdir(ruta):
        raise FileAccessError(f"'{ruta}' es una carpeta, no un archivo")
    try:
        with open(ruta, encoding="utf-8", newline="") as fh:
            return fh.read()
    except FileNotFoundError:
        raise FileAccessError(f"no existe el archivo '{ruta}'") from None
    except UnicodeDecodeError:
        raise FileAccessError(f"'{ruta}' no es texto UTF-8") from None
    except OSError:
        raise FileAccessError(f"no se pudo leer '{ruta}'") from None


def _tamano(ruta: Any) -> int:
    ruta = str(ruta)
    if os.path.isdir(ruta):
        raise FileAccessError(f"'{ruta}' es una carpeta, no un archivo")
    if not os.path.exists(ruta):
        raise FileAccessError(f"no existe el archivo '{ruta}'")
    try:
        return os.path.getsize(ruta)
    except OSError:
        raise FileAccessError(f"no se pudo leer '{ruta}'") from None


def _leer_bytes(ruta: Any, bloque: Any, n: Any) -> None:
    """Los ``n`` primeros bytes de ``ruta``, en las celdas de ``bloque``."""
    ruta = str(ruta)
    try:
        with open(ruta, "rb") as fh:
            datos = fh.read(n)
    except FileNotFoundError:
        raise FileAccessError(f"no existe el archivo '{ruta}'") from None
    except OSError:
        raise FileAccessError(f"no se pudo leer '{ruta}'") from None
    if not isinstance(bloque, Block) or len(datos) != n or n > len(bloque):
        raise FileAccessError(f"no se pudo leer '{ruta}'")
    for i, octeto in enumerate(datos):
        bloque.cells[i].write(octeto)


def _escribir_bytes(ruta: Any, bloque: Any, n: Any) -> None:
    """Las ``n`` primeras celdas de ``bloque``, como bytes, en ``ruta``."""
    ruta = str(ruta)
    if not isinstance(bloque, Block) or n > len(bloque):
        raise FileAccessError(f"no se pudo escribir '{ruta}'")
    datos = bytes((c.value or 0) & 0xFF for c in bloque.cells[:n])
    try:
        with open(ruta, "wb") as fh:
            fh.write(datos)
    except OSError:
        raise FileAccessError(f"no se pudo escribir '{ruta}'") from None


# --------------------------------------------------------------------------- #
# lib/text: cadenas (los indices cuentan CODE POINTS, como 's[i]')
# --------------------------------------------------------------------------- #

def _trozo(s: str, desde: int, hasta: int) -> str:
    if not (0 <= desde <= hasta <= len(s)):
        raise IndexOutOfRangeError(
            f"el trozo [{desde}, {hasta}) no cabe en una cadena de {len(s)} "
            "caracteres")
    return s[desde:hasta]


def _buscar(s: str, parte: str, desde: int) -> int:
    if not (0 <= desde <= len(s)):
        raise IndexOutOfRangeError(
            f"buscar desde {desde} en una cadena de {len(s)} caracteres")
    return s.find(parte, desde)


def _unir(partes: Any, n: int, separador: str) -> str:
    if not isinstance(partes, Block) or not (0 <= n <= len(partes)):
        raise IndexOutOfRangeError(f"unir {n} partes de un bloque que no las tiene")
    return separador.join(str(c.value) for c in partes.cells[:n])


def _entero_de(s: str) -> int:
    cuerpo = s[1:] if s[:1] in ("+", "-") else s
    if not cuerpo or not all("0" <= c <= "9" for c in cuerpo):
        raise ConversionError(f"'{s}' no es un entero")
    valor = int(s)
    if not (-(1 << 63) <= valor < (1 << 63)):
        raise ConversionError(f"'{s}' no cabe en un int")
    return valor


#: '[+-]digitos[.digitos][e[+-]digitos]': la gramatica de 'text.parse_float'
#: (la misma que comprueba la VM, antes de convertir)
_FLOTANTE = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")


def _flotante_de(s: str) -> float:
    """Redondeo CORRECTO: ``float()`` de Python da el ``double`` mas cercano
    al decimal escrito, igual que ``strtod`` en la VM."""
    if _FLOTANTE.fullmatch(s) is None:
        raise ConversionError(f"'{s}' no es un float")
    valor = float(s)
    if math.isinf(valor):
        raise ConversionError(f"'{s}' no cabe en un float")
    return valor


def _bits_de_float(x: float) -> int:
    return struct.unpack("<q", struct.pack("<d", float(x)))[0]


def _float_de_bits(bits: int) -> float:
    return struct.unpack("<d", struct.pack("<q", bits))[0]


def _utf8_largo(s: str) -> int:
    return len(s.encode("utf-8"))


def _utf8_a_bytes(s: str, destino: Any, n: int) -> None:
    datos = s.encode("utf-8")
    if not isinstance(destino, Block) or len(datos) != n or n > len(destino):
        raise IndexOutOfRangeError(f"{n} bytes no caben en el bloque")
    for i, octeto in enumerate(datos):
        destino.cells[i].write(octeto)


def _utf8_de_bytes(datos: Any, n: int) -> str:
    if not isinstance(datos, Block) or not (0 <= n <= len(datos)):
        raise IndexOutOfRangeError(f"{n} bytes de un bloque que no los tiene")
    crudo = bytes((c.value or 0) & 0xFF for c in datos.cells[:n])
    try:
        return crudo.decode("utf-8")
    except UnicodeDecodeError:
        raise ConversionError("los bytes no son UTF-8 valido") from None


def _escribir_archivo(ruta: Any, texto: Any) -> None:
    ruta = str(ruta)
    try:
        with open(ruta, "w", encoding="utf-8", newline="") as fh:
            fh.write(str(texto))
    except OSError:
        raise FileAccessError(f"no se pudo escribir '{ruta}'") from None


def _existe(ruta: Any) -> bool:
    return os.path.exists(str(ruta))


def _listado(ruta: str) -> List[str]:
    if not os.path.exists(ruta):
        raise FileAccessError(f"no existe la carpeta '{ruta}'")
    if not os.path.isdir(ruta):
        raise FileAccessError(f"'{ruta}' no es una carpeta")
    try:
        return sorted(os.listdir(ruta))
    except OSError:
        raise FileAccessError(f"no se pudo listar '{ruta}'") from None


def _entradas(ruta: Any) -> int:
    ruta = str(ruta)
    _LISTADO.clear()
    _LISTADO[ruta] = _listado(ruta)
    return len(_LISTADO[ruta])


def _entrada(ruta: Any, i: Any) -> str:
    ruta = str(ruta)
    nombres = _LISTADO.get(ruta)
    if nombres is None:
        nombres = _LISTADO[ruta] = _listado(ruta)
    if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(nombres):
        raise IndexOutOfRangeError(
            f"entrada {i} fuera de rango [0, {len(nombres)})")
    return nombres[i]


def _argumentos() -> int:
    return len(_ARGUMENTOS)


def _argumento(i: Any) -> str:
    if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(_ARGUMENTOS):
        raise IndexOutOfRangeError(
            f"argumento {i} fuera de rango [0, {len(_ARGUMENTOS)})")
    return _ARGUMENTOS[i]


def _salir(codigo: Any) -> None:
    """Termina el programa AHORA, sin desenrollar: no corren los '__free__'
    pendientes (como 'std::exit' en C++ u 'os._exit' en Python). Lo que ya se
    escribió se vuelca antes de salir."""
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(int(codigo))


def _escribir_error(texto: Any) -> None:
    sys.stderr.write(str(texto))


# --- lib/sistema/rutas: 'os.path' tal cual --------------------------------- #
# Son las MISMAS funciones que usa el compilador (V0) para ubicar librerías y
# escribir sus rutas en el .phir: la V1, que compila en suriaX, tiene que
# producir exactamente las mismas cadenas. La VM las reimplementa en C++ con
# los algoritmos de 'ntpath'/'posixpath' y la prueba diferencial las compara.

def _entorno(nombre: Any) -> str:
    return os.environ.get(str(nombre), "")


RUTAS: Dict[str, Callable[..., Any]] = {
    "__directorio_actual__": os.getcwd,
    "__entorno__": _entorno,
    "__separador__": lambda: os.sep,
    "__absoluta__": lambda r: os.path.abspath(str(r)),
    "__normaliza__": lambda r: os.path.normpath(str(r)),
    "__une__": lambda a, b: os.path.join(str(a), str(b)),
    "__carpeta_de__": lambda r: os.path.dirname(str(r)),
    "__nombre_de__": lambda r: os.path.basename(str(r)),
    "__es_carpeta__": lambda r: os.path.isdir(str(r)),
    "__es_archivo__": lambda r: os.path.isfile(str(r)),
}


REGISTRY: Dict[str, Callable[..., Any]] = {
    # primitivas base de IO: 'suriax_write' (docs/examples/io.libsrx) y
    # '__write__' (lib/io/print.libsrx). Ambas escriben una cadena a stdout;
    # son el mismo servicio del host bajo los dos nombres del ecosistema.
    "suriax_write": _suriax_write,
    "__write__": _suriax_write,
    # primitivas de MEMORIA (lib/mem): reserva cruda + copia de bloques, la
    # base sobre la que se construye un vector SIN meter cada hook en el
    # compilador (mismo patrón prototipo+intrínseco que __write__).
    "__reserve__": _suriax_reserve,
    "__copy__": _suriax_copy,
    "__release__": _suriax_release,
    "__take__": _suriax_take,
    "__move__": _suriax_move,
    # llamadas al host de 'lib/sistema'
    "__leer_archivo__": _leer_archivo,
    "__escribir_archivo__": _escribir_archivo,
    "__existe__": _existe,
    "__entradas__": _entradas,
    "__entrada__": _entrada,
    "__argumentos__": _argumentos,
    "__argumento__": _argumento,
    "__salir__": _salir,
    "__escribir_error__": _escribir_error,
    "__tamano__": _tamano,
    # lib/text
    "__trozo__": _trozo,
    "__buscar__": _buscar,
    "__empieza__": lambda s, p: s.startswith(p),
    "__termina__": lambda s, p: s.endswith(p),
    "__unir__": _unir,
    "__entero_de__": _entero_de,
    "__flotante_de__": _flotante_de,
    "__bits_de_float__": _bits_de_float,
    "__float_de_bits__": _float_de_bits,
    "__utf8_largo__": _utf8_largo,
    "__utf8_a_bytes__": _utf8_a_bytes,
    "__utf8_de_bytes__": _utf8_de_bytes,
    "__leer_bytes__": _leer_bytes,
    "__escribir_bytes__": _escribir_bytes,
    # lib/sistema/rutas
    **RUTAS,
}


def register(name: str, fn: Callable[..., Any]) -> None:
    """Punto de extensión del host (p. ej. tests o un REPL embebido)."""
    REGISTRY[name] = fn


def lookup(name: str) -> Callable[..., Any] | None:
    return REGISTRY.get(name)


__all__ = ["REGISTRY", "CASTS", "ANCHOS", "register", "lookup", "lookup_cast",
           "fijar_argumentos"]
