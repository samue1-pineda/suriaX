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
import struct
import sys
from typing import Any, Callable, Dict

from .errors import IndexOutOfRangeError, InvalidCastRuntimeError, NotIndexableError
from .memory.block import Block


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
    for i in range(n):
        dst.cells[i].write(src.cells[i].read())


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
    """Conversión nativa hacia el tipo nominal ``destino``, si el host la trae."""
    return CASTS.get(destino)


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
}


def register(name: str, fn: Callable[..., Any]) -> None:
    """Punto de extensión del host (p. ej. tests o un REPL embebido)."""
    REGISTRY[name] = fn


def lookup(name: str) -> Callable[..., Any] | None:
    return REGISTRY.get(name)


__all__ = ["REGISTRY", "CASTS", "ANCHOS", "register", "lookup", "lookup_cast"]
