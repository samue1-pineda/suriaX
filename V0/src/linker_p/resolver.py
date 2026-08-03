"""Resolución de RUTAS: de un nombre de import a un archivo/carpeta en disco.

Solo I/O de localización (``os.path.isfile``) — ni parseo ni semántica. Es
la parte más caliente del linker (se ejecuta por cada ``#import``), así que
todo aquí es O(1) en stats por candidato, sin listar directorios.

**Rutas de búsqueda**, en orden: (1) el directorio del fuente que importa,
(2) las rutas de ``libraries.libsrx_paths`` del ``.suriaX_config.yaml``,
resueltas RELATIVAS A LA RAÍZ DEL PROYECTO (``config["_root"]``, el
directorio del yaml) — nunca al CWD del proceso. Default: ``./lib``.

**Archivo padre de un paquete**: una carpeta es un paquete si contiene
``main.libsrx`` (convención) o ``<carpeta>.libsrx`` (compatibilidad
histórica), y ese archivo termina en ``#export package as <alias>``. El
nombre del ARCHIVO solo localiza; el nombre público del paquete lo da su
alias (ver ``packages.py``).

**Nombre de archivo**: exacto y, como cortesía, en minúsculas (``#import
IO`` encuentra ``io/``). El alias declarado es quien manda: la cortesía solo
evita fallar por el case de una CARPETA.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

# rutas por defecto si no hay configuracion cargada (espejo del default de
# 'libraries.libsrx_paths' en config/yaml_config.py — el linker no importa
# el paquete config/ para mantenerse independiente; main.py pasa la config).
_DEFAULT_PATHS: Tuple[str, ...] = ("./lib",)

LIBSRX_EXT = ".libsrx"
SRCX_EXT = ".srcx"

#: Nombre canónico del archivo padre de un paquete (convención).
PACKAGE_PARENT = "main" + LIBSRX_EXT


@dataclass(slots=True, frozen=True)
class Found:
    """Resultado de :func:`find_library`.

    ``kind``: ``"libsrx"`` (archivo suelto), ``"package"`` (carpeta),
    ``"srcx"`` (fuente usado como librería -> NOTA). ``parent`` solo se
    rellena para ``"package"``: la ruta del archivo padre ya localizada, así
    ``packages.py`` no repite los stats que esta función ya hizo.
    """
    path: str
    kind: str
    parent: Optional[str] = None


def _project_resolve(config: Optional[dict], path: str) -> str:
    """Ruta relativa -> anclada a la raíz del proyecto (``config['_root']``,
    el directorio del ``.suriaX_config.yaml``; fallback CWD). Regla espejo
    de ``config/yaml_config.resolve_path`` — duplicada a propósito para que
    el linker no dependa del paquete ``config/``."""
    path = os.path.expanduser(path)
    if os.path.isabs(path):
        return path
    root = (config or {}).get("_root") or os.getcwd()
    return os.path.normpath(os.path.join(root, path))


def search_paths(source_path: Optional[str], config: Optional[dict]) -> List[str]:
    """Rutas de búsqueda en orden: dir del fuente, luego la configuración
    (resuelta contra la raíz del proyecto, nunca contra el CWD)."""
    paths: List[str] = []
    if source_path:
        paths.append(os.path.dirname(os.path.abspath(source_path)))
    configured = None
    if config is not None:
        configured = (config.get("libraries") or {}).get("libsrx_paths")
    for p in configured if configured else _DEFAULT_PATHS:
        paths.append(_project_resolve(config, p))
    return paths


def _name_candidates(lib: str) -> Tuple[str, ...]:
    """``lib`` y su versión en minúsculas, sin duplicar el stat si coinciden."""
    lower = lib.lower()
    return (lib,) if lib == lower else (lib, lower)


def package_parent(dir_path: str, folder_name: str) -> Optional[str]:
    """Archivo padre de la carpeta-paquete ``dir_path``, o ``None``.

    Orden: ``main.libsrx`` (convención actual) y, como compatibilidad,
    ``<carpeta>.libsrx``. Máximo 2 stats, sin listar el directorio.
    """
    candidate = os.path.join(dir_path, PACKAGE_PARENT)
    if os.path.isfile(candidate):
        return candidate
    candidate = os.path.join(dir_path, folder_name + LIBSRX_EXT)
    if os.path.isfile(candidate):
        return candidate
    return None


def find_library(lib: str, paths: List[str], *,
                 packages_only: bool = False) -> Optional[Found]:
    """Localiza ``lib`` en ``paths`` y devuelve un :class:`Found`, o ``None``.

    Orden de preferencia por base: archivo ``.libsrx`` > paquete > ``.srcx``.

    ``packages_only``: un import PUNTEADO (``io.string``) solo puede
    satisfacerlo un paquete — los archivos planos homónimos se ignoran en
    vez de ganar por orden de búsqueda y bloquear el submódulo.
    """
    names = _name_candidates(lib)
    for base in paths:
        if not packages_only:
            for name in names:
                candidate = os.path.join(base, name + LIBSRX_EXT)
                if os.path.isfile(candidate):
                    return Found(os.path.abspath(candidate), "libsrx")
        for name in names:
            dir_path = os.path.join(base, name)
            parent = package_parent(dir_path, name)
            if parent is not None:
                return Found(os.path.abspath(dir_path), "package",
                             os.path.abspath(parent))
        if not packages_only:
            for name in names:
                candidate = os.path.join(base, name + SRCX_EXT)
                if os.path.isfile(candidate):
                    return Found(os.path.abspath(candidate), "srcx")
    return None


__all__ = [
    "Found", "search_paths", "find_library", "package_parent",
    "PACKAGE_PARENT", "LIBSRX_EXT", "SRCX_EXT",
]
