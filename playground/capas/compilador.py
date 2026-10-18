"""Adaptador del compilador: el frontend de verdad, dentro del proceso.

El compilador se importa como LIBRERÍA (``driver/artifacts``), igual que lo
hará cualquier otra herramienta. Este módulo es el único del playground que lo
nombra, y hace dos cosas que el compilador no tiene por qué hacer:

* **Lo llama de uno en uno.** El frontend guarda estado global (la caché del
  enlazador, entre otros) y el servidor atiende con hilos: dos compilaciones a
  la vez se pisaban y un programa válido salía con ``SEM010``. Medido: 10 de
  90 compilaciones en paralelo daban un resultado distinto al de la serie.
* **No deja pasar una excepción.** Un fallo del compilador es un dato de la
  respuesta (``error_interno``), no un 500 que deja a la página sin nada.

Límite conocido: una compilación que no termine retiene el candado y nadie más
compila. No hay forma de cortar un hilo de Python; lo acota el tamaño máximo
del fuente y lo arreglaría aislar el compilador en un proceso.
"""

from __future__ import annotations

import os
import sys
import threading
import traceback

from . import config
from .estados import (ERROR_DEL_PROGRAMA, ERROR_INTERNO, NO_DISPONIBLE, OK,
                      proveedor, sin_rutas)

for _p in (config.REPO, os.path.join(config.REPO, "V0")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

#: las fases que entrega el frontend, en orden. Cuando el compilador falla por
#: dentro, la respuesta las trae todas igual, cada una con su motivo: un panel
#: que falta se confunde con una pestaña que no existe.
FASES = ("tokens", "ast", "typed_ast", "symbols", "hir", "link")

#: severidades que detienen la compilación (las de ``error_handler``).
_DETIENEN = ("critical", "panic")

_CANDADO = threading.Lock()

_ARCHIVO = "playground.srcx"


def _recolectar(fuente: str) -> dict:
    from driver.artifacts import collect
    return collect(fuente, path=_ARCHIVO)


def _solo_lexico(fuente: str) -> dict:
    from driver.artifacts import lex_only
    return lex_only(fuente, path=_ARCHIVO)


def _anotar(exc: BaseException) -> str:
    """Deja la traza en el registro del servidor y devuelve lo publicable.

    La traza lleva rutas de la máquina; a quien llama le basta el tipo y el
    mensaje para buscar el fallo.
    """
    traceback.print_exception(type(exc), exc, exc.__traceback__,
                              file=sys.stderr)
    return f"{type(exc).__name__}: {exc}"


def compilar(fuente: str) -> tuple:
    """Todas las fases del frontend. Devuelve ``(payload, proveedor)``.

    El ``payload`` es el de ``driver.artifacts.collect``; cuando el compilador
    falla por dentro es uno vacío con la misma forma.
    """
    try:
        with _CANDADO:
            payload = _recolectar(fuente)
    except Exception as exc:  # noqa: BLE001 - el fallo es un dato, no un 500
        detalle = _anotar(exc)
        motivo = f"el compilador falló por dentro ({detalle})"
        return ({"source": fuente, "path": _ARCHIVO, "diagnostics": [],
                 "phases": {fase: {"ok": False, "status": ERROR_INTERNO,
                                   "reason": motivo} for fase in FASES}},
                proveedor(ERROR_INTERNO, detalle))

    # el compilador nombra rutas de ESTA máquina en algunos mensajes ("rutas
    # probadas: ..."): en la CLI ayudan, a un visitante solo le cuentan cómo
    # está montado el servidor.
    for diag in payload["diagnostics"]:
        diag["message"] = sin_rutas(diag["message"])

    if "phir" in payload:
        propio = proveedor(OK)
    elif any(d.get("severity") in _DETIENEN for d in payload["diagnostics"]):
        propio = proveedor(ERROR_DEL_PROGRAMA)
    else:
        # sin HIR y sin un error del programa: al entorno le falta algo
        propio = proveedor(NO_DISPONIBLE,
                           payload["phases"].get("hir", {}).get("reason", ""))
    # cada fase dice su estado con el mismo vocabulario que los proveedores:
    # la que no se produjo es por lo mismo por lo que el compilador no llegó.
    for fase in payload["phases"].values():
        fase["status"] = OK if fase.get("ok") else propio["status"]
    return payload, propio


def lexico(fuente: str) -> tuple:
    """Solo el análisis léxico. Devuelve ``(payload, proveedor)``."""
    try:
        with _CANDADO:
            return _solo_lexico(fuente), proveedor(OK)
    except Exception as exc:  # noqa: BLE001
        return ({"tokens": [], "diagnostics": []},
                proveedor(ERROR_INTERNO, _anotar(exc)))


def salud() -> dict:
    """¿Puede compilar este entorno? No compila nada: mira que esté todo."""
    try:
        from driver import artifacts  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return proveedor(ERROR_INTERNO, _anotar(exc))
    try:
        from src.HIR.stubs import load_hir_pb2
        load_hir_pb2()
    except Exception as exc:  # noqa: BLE001 - protobuf no instalado
        return proveedor(NO_DISPONIBLE,
                         f"la fase HIR necesita protobuf: {exc}")
    return proveedor(OK)
