"""Verificador de caché de build (``./build/cache``).

Módulo del paquete ``config/``. El build system (**suriniX**) y el runtime
system aún no existen (ROADMAP Fase 10), pero esta es su **puerta de
entrada**: define DÓNDE vive la caché, su manifiesto y la regla de
invalidación, para que cuando esas piezas lleguen no haya que decidir (ni
migrar) nada de esto.

Contenido hoy:

 - ``ensure_cache_dir``: crea/verifica ``cache.dir`` del yaml
   (default ``./build/cache``, relativo a la raíz del proyecto).
 - manifiesto ``manifest.json``: mapa ``clave -> {path, mtime, size}``.
   La clave es la ruta absoluta del archivo origen (p. ej. una ``.libsrx``
   parseada); la invalidación es por **mtime + tamaño** (barata y
   suficiente para archivos locales; si el objetivo WIP exige más, se
   cambia por hash de contenido AQUÍ y en ningún otro sitio).
 - ``verify_cache``: poda del manifiesto las entradas cuyo origen cambió o
   desapareció, y devuelve el reporte.

La caché en memoria de librerías (``src/linker_p/cache.py``) es independiente
(vive un proceso); este módulo es la versión PERSISTENTE entre procesos que
suriniX consumirá.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from .yaml_config import resolve_path

MANIFEST_FNAME = "manifest.json"


def cache_dir(config: Optional[dict]) -> str:
    cache_cfg = (config or {}).get("cache") or {}
    return resolve_path(config, cache_cfg.get("dir", "./build/cache"))


def cache_enabled(config: Optional[dict]) -> bool:
    cache_cfg = (config or {}).get("cache") or {}
    return bool(cache_cfg.get("enabled", True))


def ensure_cache_dir(config: Optional[dict]) -> str:
    """Crea (si hace falta) y devuelve el directorio de caché."""
    directory = cache_dir(config)
    os.makedirs(directory, exist_ok=True)
    return directory


def _manifest_path(config: Optional[dict]) -> str:
    return os.path.join(cache_dir(config), MANIFEST_FNAME)


def load_manifest(config: Optional[dict]) -> dict:
    path = _manifest_path(config)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}  # manifiesto corrupto: se regenera, nunca se aborta por caché


def save_manifest(config: Optional[dict], manifest: dict) -> None:
    ensure_cache_dir(config)
    with open(_manifest_path(config), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)


def stamp(path: str) -> Optional[dict]:
    """Huella barata de un archivo origen (mtime + size), o ``None``."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return {"path": path, "mtime": st.st_mtime, "size": st.st_size}


def is_fresh(manifest: dict, key: str) -> bool:
    """¿La entrada ``key`` del manifiesto sigue vigente?"""
    entry = manifest.get(key)
    if not entry:
        return False
    current = stamp(entry.get("path", key))
    return (
        current is not None
        and current["mtime"] == entry.get("mtime")
        and current["size"] == entry.get("size")
    )


def verify_cache(config: Optional[dict]) -> dict:
    """Verifica el manifiesto completo: poda entradas obsoletas.

    Devuelve ``{"dir", "total", "fresh", "pruned"}``. Nunca lanza: una caché
    rota se descarta, no bloquea la compilación.
    """
    if not cache_enabled(config):
        return {"dir": cache_dir(config), "total": 0, "fresh": 0, "pruned": 0}

    manifest = load_manifest(config)
    fresh = {k: v for k, v in manifest.items() if is_fresh(manifest, k)}
    pruned = len(manifest) - len(fresh)
    if pruned:
        save_manifest(config, fresh)
    return {
        "dir": cache_dir(config),
        "total": len(manifest),
        "fresh": len(fresh),
        "pruned": pruned,
    }


__all__ = [
    "cache_dir", "cache_enabled", "ensure_cache_dir",
    "load_manifest", "save_manifest", "stamp", "is_fresh", "verify_cache",
    "MANIFEST_FNAME",
]
