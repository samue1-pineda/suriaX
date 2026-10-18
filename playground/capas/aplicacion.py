"""Capa de aplicación: qué se le pide a cada proveedor y cómo se junta.

No sabe de HTTP ni de procesos. Recibe un fuente, devuelve un diccionario, y
es lo que otra herramienta importaría si quisiera las fases sin pasar por el
servidor.

La propiedad que mantiene: **cada proveedor responde por lo suyo**. Si el
target web falla, las fases del frontend llegan intactas; si falla el
compilador, la respuesta sigue teniendo la misma forma y dice quién falló.
"""

from __future__ import annotations

import time

from . import compilador, config, web
from .estados import peor


def _firmar(payload: dict, **proveedores: dict) -> dict:
    payload["api"] = config.API
    payload["providers"] = proveedores
    payload["status"] = peor(*(p["status"] for p in proveedores.values()))
    return payload


def compile_source(source: str, *, debug: bool = False) -> dict:
    """Todas las fases del fuente, incluidas las del backend web.

    ``debug`` añade lo que el compilador mide de sí mismo —cuánto tarda cada
    fase y cuánto produce—, que es lo que ``--debug`` vuelca en la CLI. No
    cambia lo que se compila: es la misma corrida, contada.
    """
    inicio = time.perf_counter()
    payload, del_compilador = compilador.compilar(source)
    frontend = time.perf_counter() - inicio

    inicio = time.perf_counter()
    # el .phir y las unidades NO viajan al navegador: son bytes y la página
    # no los usa. Se sacan aquí, que es donde se le entregan al target.
    fases, diagnosticos, del_web = web.bajar(payload.pop("phir", None),
                                             payload.pop("units", {}))
    payload["phases"].update(fases)
    payload["diagnostics"].extend(diagnosticos)
    en_web = time.perf_counter() - inicio

    if debug:
        tokens = payload["phases"].get("tokens", {}).get("tokens") or []
        enlace = payload["phases"].get("link", {})
        payload["debug"] = {
            "times": {"frontend": round(frontend * 1000, 2),
                      "target web": round(en_web * 1000, 2)},
            "metrics": {
                "bytes del fuente": len(source.encode()),
                "líneas": source.count("\n") + 1,
                "tokens": len(tokens),
                "diagnósticos": len(payload["diagnostics"]),
                "librerías ligadas": len(enlace.get("libraries") or []),
                "hooks": len(enlace.get("hooks") or []),
                "conversiones": len(enlace.get("casts") or []),
            },
        }
    return _firmar(payload, compiler=del_compilador, web=del_web)


def lex_source(source: str) -> dict:
    """Solo el léxico: lo que el editor pide en cada pausa al escribir."""
    payload, del_compilador = compilador.lexico(source)
    return _firmar(payload, compiler=del_compilador)


def health() -> dict:
    """El estado de cada proveedor, sin compilar nada."""
    return _firmar({}, compiler=compilador.salud(), web=web.salud())
