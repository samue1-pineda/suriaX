"""Caché de librerías POR COMPILACIÓN + guard de imports circulares.

Toda ``.libsrx`` / paquete se parsea UNA vez por proceso, cacheada por su
ruta ABSOLUTA: un compilador batch de M fuentes que importen la misma
librería la carga una sola vez. La caché PERSISTENTE entre procesos es otra
cosa y vive en ``config/cache.py`` (suriniX, futuro).

**Caché negativa** (``_FAILED``): una librería que NO se pudo cargar también
se recuerda. Sin esto, una lib rota importada desde N sitios se reparsea N
veces y emite su diagnóstico N veces (p. ej. ``print.libsrx``, importada por
el padre de su paquete Y descubierta como submódulo, se reportaba doble). El
contrato es el mismo que el del resto de la fase: **cada problema se reporta
una vez, con la ruta del archivo que lo contiene**.

**Vive una compilación, no el proceso.** Cada compilación o análisis de
nivel superior (``compile_source``, ``emit_diagnostics``, ``emit_stage``,
``artifacts.collect``) empieza con :func:`nueva_compilacion`. Antes vivía
el proceso entero: en uno largo —el playground, un LSP en proceso— la
segunda compilación de un programa con una librería rota ya no mostraba sus
errores (la caché negativa decía "ya se dijeron"), y una librería editada
seguía sirviéndose vieja (la positiva no mira el archivo).

El guard de ciclos (``_LOADING``) detecta ``A importa B importa A`` sin
recursión infinita: es un ``set`` de rutas en curso de carga.
"""

from __future__ import annotations

from typing import Dict, Optional, Set

from .library import LoadedLibrary

# ruta absoluta (archivo o carpeta de paquete) -> librería ya cargada.
_CACHE: Dict[str, LoadedLibrary] = {}
# rutas que ya fallaron: su diagnóstico ya se emitió, no se reintentan.
_FAILED: Set[str] = set()
# rutas actualmente en carga: si una reaparece, hay un ciclo de imports.
_LOADING: Set[str] = set()


def get(path: str) -> Optional[LoadedLibrary]:
    return _CACHE.get(path)


def put(path: str, library: LoadedLibrary) -> None:
    _CACHE[path] = library


def has_failed(path: str) -> bool:
    """¿Esta ruta ya se intentó cargar y falló? (su error ya está reportado)"""
    return path in _FAILED


def mark_failed(path: str) -> None:
    _FAILED.add(path)


def is_loading(path: str) -> bool:
    return path in _LOADING


def mark_loading(path: str) -> None:
    _LOADING.add(path)


def unmark_loading(path: str) -> None:
    _LOADING.discard(path)


def clear_cache() -> None:
    """Vacía la caché (positiva y negativa) y el guard de ciclos."""
    _CACHE.clear()
    _FAILED.clear()
    _LOADING.clear()


def nueva_compilacion() -> None:
    """Empieza una compilación: lo cargado por la anterior no vale (sus
    archivos pudieron cambiar, y sus errores hay que volver a decirlos)."""
    clear_cache()


__all__ = [
    "get", "put", "has_failed", "mark_failed", "is_loading", "mark_loading",
    "unmark_loading", "clear_cache", "nueva_compilacion",
]
