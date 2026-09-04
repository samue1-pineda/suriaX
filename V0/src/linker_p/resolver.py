"""Resolución de RUTAS: de un nombre de import a un archivo/carpeta en disco.

Solo I/O de localización (``os.path.isfile``) — ni parseo ni semántica. Es
la parte más caliente del linker (se ejecuta por cada ``#import``), así que
todo aquí es O(1) en stats por candidato, sin listar directorios.

**Rutas de búsqueda**, en orden:

1. el directorio del fuente que importa;
2. las rutas de ``libraries.libsrx_paths`` del ``.suriaX_config.yaml``,
   resueltas RELATIVAS A LA RAÍZ DEL PROYECTO (``config["_root"]``, el
   directorio del yaml) — nunca al CWD del proceso. Default: ``./lib``;
3. la **librería estándar que trae el compilador**.

El tercer escalón separa dos cosas que estaban mezcladas: las librerías que
trae el COMPILADOR (``io``, ``mem``, ``array``…) y las que escribe el
USUARIO. Sin él, ``io`` solo se encontraba si el proyecto tenía su propia
copia de ``lib/`` al lado del fuente — así que un programa fuera del
repositorio no compilaba aunque solo usara la stdlib, y cada prueba tenía que
copiarse el árbol entero.

Va el ÚLTIMO a propósito: una librería del usuario con el mismo nombre gana
siempre. La stdlib es un respaldo, no una prioridad, y así un proyecto puede
sustituir cualquier pieza sin tocar el compilador.

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

#: Variable de entorno que fija dónde vive la stdlib. Existe para el día en
#: que el compilador se instale fuera de su árbol de fuentes: entonces el
#: cálculo de abajo deja de valer y esto es lo que lo dice.
STDLIB_ENV = "SURIAX_STDLIB"


def stdlib_path() -> Optional[str]:
    """El ``lib/`` que trae el compilador, o ``None`` si no está.

    Se deriva de la ubicación de ESTE archivo
    (``<raiz>/V0/src/linker_p/resolver.py`` -> ``<raiz>/lib``) y no de la
    configuración: la pregunta "¿dónde estoy instalado?" no es del proyecto
    del usuario, es del compilador. Mezclarlas es lo que obligaba a que cada
    proyecto declarara la stdlib en su yaml.

    ``None`` en vez de una ruta inventada: si el árbol no está donde se
    espera, es mejor que el diagnóstico de "no se encontró" liste las rutas
    reales a que liste una que no existe.
    """
    desde_entorno = os.environ.get(STDLIB_ENV)
    if desde_entorno:
        ruta = os.path.abspath(os.path.expanduser(desde_entorno))
        return ruta if os.path.isdir(ruta) else None
    # <raiz>/V0/src/linker_p/resolver.py -> <raiz>
    raiz = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                        "..", "..", ".."))
    ruta = os.path.join(raiz, "lib")
    return ruta if os.path.isdir(ruta) else None

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
    """Rutas de búsqueda, en orden: dir del fuente, la configuración del
    proyecto (resuelta contra su raíz, nunca contra el CWD) y, al final, la
    stdlib del compilador.

    Sin duplicados: la stdlib no se repite si el proyecto ya la declaró, y
    así el diagnóstico de "no se encontró" no lista dos veces la misma ruta.
    """
    paths: List[str] = []
    if source_path:
        paths.append(os.path.dirname(os.path.abspath(source_path)))
    configured = None
    if config is not None:
        configured = (config.get("libraries") or {}).get("libsrx_paths")
    for p in configured if configured else _DEFAULT_PATHS:
        paths.append(_project_resolve(config, p))
    stdlib = stdlib_path()
    if stdlib is not None:
        paths.append(stdlib)
    vistas: set = set()
    return [p for p in paths if not (p in vistas or vistas.add(p))]


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
