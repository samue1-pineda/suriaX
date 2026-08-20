"""Lectura de ``extends.srcx`` — el manifiesto de extensiones del proyecto.

Formato (una clave por línea, ``#`` comenta hasta el fin de línea)::

    # extends.srcx
    project:   MiJuego
    logic_dir: extensions/logic     # C++: la LÓGICA (llega con la VM+JIT)
    calls_dir: extensions/calls     # Python: las DECLARACIONES

**Por qué un parser propio y no el lexer del lenguaje.** Esta capa corre
ANTES del análisis léxico: usar ``Lexer``/``Parser`` para leer el manifiesto
crearía una dependencia circular (el manifiesto configura al compilador que
lo leería) y metería en la gramática de suriaX unas directivas que no son
código del lenguaje. La extensión ``.srcx`` es cosmética — el contenido es un
formato de configuración, y este módulo es su única definición.

Son ~100 líneas porque el formato es deliberadamente diminuto, y a cambio
cada diagnóstico sale con **línea y columna reales** del manifiesto, que es
lo que un editor necesita para subrayar.

Las rutas del manifiesto son relativas a la RAÍZ DEL PROYECTO (el directorio
donde vive, que es también donde vive ``.suriaX_config.yaml``), nunca al CWD
del proceso — misma regla que ``config/yaml_config.resolve_path``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .errors import (EXT001, EXT002, EXT003, EXT004, EXT005, EXT006, EXT007,
                     ExtensionError)

#: nombre fijo del manifiesto; se busca en la raíz del proyecto.
MANIFEST_FNAME = "extends.srcx"

#: claves aceptadas. ``calls_dir`` es la única obligatoria: sin declaraciones
#: no hay extensión que registrar. ``logic_dir`` es opcional a propósito — la
#: lógica C++ solo puede existir cuando exista la VM+JIT, y un proyecto que
#: aún declara sin implementar tiene que poder compilar.
_KEYS = ("project", "logic_dir", "calls_dir")
_REQUIRED = ("calls_dir",)
_DIR_KEYS = ("logic_dir", "calls_dir")


@dataclass(frozen=True)
class Manifest:
    """``extends.srcx`` ya leído, validado y con las rutas RESUELTAS."""

    path: str                      #: ruta absoluta del propio manifiesto
    root: str                      #: raíz del proyecto (dir del manifiesto)
    project: str                   #: puede venir vacío: lo define el .py
    logic_dir: Optional[str]       #: absoluto, o None si no se declaró
    calls_dir: str                 #: absoluto
    #: (clave, valor crudo, línea) en orden de aparición — para ``--emit-extensions``
    entries: Tuple[Tuple[str, str, int], ...] = ()


def manifest_path(root: str) -> str:
    """Ruta donde se busca el manifiesto de un proyecto."""
    return os.path.join(root, MANIFEST_FNAME)


def exists(root: str) -> bool:
    return os.path.isfile(manifest_path(root))


def _split_line(raw: str) -> str:
    """Quita el comentario ``#`` de una línea.

    No hay escapes: una ruta con ``#`` no es representable, y es preferible a
    inventar un mecanismo de escapado para un formato de tres claves.
    """
    head, _, _ = raw.partition("#")
    return head


def _unquote(value: str) -> str:
    """Comillas OPCIONALES: ``calls_dir: "mis extensiones"`` y
    ``calls_dir: extensions/calls`` son ambos válidos."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse(root: str) -> Tuple[Optional[Manifest], List[ExtensionError]]:
    """Lee y valida el manifiesto de ``root``.

    Devuelve ``(None, [])`` si el proyecto no tiene manifiesto — el caso
    normal: un proyecto sin extensiones no produce ni un byte de diagnóstico.

    Acumula TODOS los errores antes de rendirse (un manifiesto con tres
    problemas los reporta los tres); con errores devuelve ``(None, errores)``.
    """
    path = manifest_path(root)
    if not os.path.isfile(path):
        return None, []

    try:
        with open(path, "rb") as fh:
            text = fh.read().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, [ExtensionError(
            EXT001, f"no se pudo leer el manifiesto de extensiones: {exc}",
            file=path)]

    errors: List[ExtensionError] = []
    values: dict[str, str] = {}
    #: clave -> (línea, columna de la CLAVE, columna del VALOR). El editor
    #: subraya el valor cuando el problema es el valor (una ruta que no
    #: existe), no la clave: por eso se guardan las dos posiciones.
    seen_at: dict[str, Tuple[int, int, int]] = {}
    entries: List[Tuple[str, str, int]] = []

    for ln, raw in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1):
        line = _split_line(raw)
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep:
            errors.append(ExtensionError(
                EXT002, f"línea malformada: se esperaba 'clave: valor' y se "
                        f"encontró {line.strip()!r}",
                file=path, line=ln, column=len(line) - len(line.lstrip()) + 1))
            continue

        column = len(key) - len(key.lstrip()) + 1
        # columna real del valor: tras los ':' y los espacios que el usuario
        # haya puesto para alinear las claves.
        value_column = len(key) + 2 + (len(value) - len(value.lstrip()))
        key = key.strip()
        value = _unquote(value.strip())

        if key not in _KEYS:
            errors.append(ExtensionError(
                EXT004, f"clave desconocida '{key}' (aceptadas: "
                        f"{', '.join(_KEYS)})",
                file=path, line=ln, column=column))
            continue
        if key in seen_at:
            errors.append(ExtensionError(
                EXT005, f"clave duplicada '{key}' (ya declarada en la línea "
                        f"{seen_at[key][0]})",
                file=path, line=ln, column=column))
            continue
        if not value:
            errors.append(ExtensionError(
                EXT006, f"la clave '{key}' no tiene valor",
                file=path, line=ln, column=value_column))
            continue

        seen_at[key] = (ln, column, value_column)
        values[key] = value
        entries.append((key, value, ln))

    for key in _REQUIRED:
        if key not in values:
            errors.append(ExtensionError(
                EXT007, f"el manifiesto no declara '{key}' (obligatoria)",
                file=path))

    # Un directorio declarado que no existe es un error del PROYECTO, no una
    # ausencia benigna: el usuario escribió una ruta y esa ruta miente.
    resolved: dict[str, str] = {}
    for key in _DIR_KEYS:
        value = values.get(key)
        if value is None:
            continue
        full = value if os.path.isabs(value) else os.path.join(root, value)
        full = os.path.normpath(os.path.expanduser(full))
        if not os.path.isdir(full):
            line, _, value_column = seen_at[key]
            errors.append(ExtensionError(
                EXT003, f"'{key}' apunta a un directorio que no existe: {value}",
                file=path, line=line, column=value_column))
            continue
        resolved[key] = full

    if errors:
        return None, errors

    return Manifest(
        path=path,
        root=root,
        project=values.get("project", ""),
        logic_dir=resolved.get("logic_dir"),
        calls_dir=resolved["calls_dir"],
        entries=tuple(entries),
    ), []


__all__ = ["MANIFEST_FNAME", "Manifest", "manifest_path", "exists", "parse"]
