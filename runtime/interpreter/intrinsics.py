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

import sys
from typing import Any, Callable, Dict

from .errors import IndexOutOfRangeError, NotIndexableError
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


__all__ = ["REGISTRY", "register", "lookup"]
