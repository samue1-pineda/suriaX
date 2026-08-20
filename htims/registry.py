"""Modelo resuelto de las extensiones de un proyecto: el :class:`ExtensionSet`.

Es la SALIDA de la capa HTIMS y su única forma pública: quien quiera saber
qué hooks aporta el usuario consulta este objeto, nunca vuelve a tocar el
disco ni a leer el manifiesto por su cuenta.

Dos fuentes, un solo modelo (ambas se validan igual):

  1. el manifiesto ``extends.srcx`` -> todos los ``.py`` de ``calls_dir``;
  2. la lista ``extensions:`` del ``.suriaX_config.yaml`` -> archivos sueltos,
     para un proyecto que prefiere configurarlo a mano o que añade uno fuera
     de ``calls_dir``.

El conjunto es inmutable y su orden es determinista (alfabético dentro del
manifiesto, luego el orden del yaml): dos corridas producen el mismo
``ExtensionSet``, byte a byte, que es lo que permite cachearlo y compararlo
en un test de snapshot.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from . import manifest as manifest_mod
from .declarations import HookDecl, scan_files
from .errors import EXT010, ExtensionError

#: archivos que nunca se escanean dentro de ``calls_dir``.
_SKIP_DIRS = ("__pycache__", ".git", ".venv", "venv", "node_modules")


@dataclass(frozen=True)
class ExtensionModule:
    """Un ``.py`` de declaraciones, con los hooks que aporta."""

    name: str                       #: basename sin extensión ('physics')
    path: str                       #: ruta absoluta
    hooks: Tuple[HookDecl, ...] = ()

    def to_dict(self) -> dict:
        return {"name": self.name, "path": self.path,
                "hooks": [h.name for h in self.hooks]}


@dataclass(frozen=True)
class ExtensionSet:
    """Todo lo que el proyecto declara vía HTIMS, ya validado."""

    root: str
    project: str
    manifest: Optional[manifest_mod.Manifest]
    logic_dir: Optional[str]
    calls_dir: Optional[str]
    modules: Tuple[ExtensionModule, ...] = ()
    hooks: Tuple[HookDecl, ...] = ()
    #: índice ``(dueño, nombre) -> declaración`` — misma clave que el HIR.
    by_key: Dict[Tuple[str, str], HookDecl] = field(default_factory=dict,
                                                    compare=False, repr=False)

    # ------------------------------------------------------------------ #
    # consulta
    # ------------------------------------------------------------------ #
    def hook(self, owner: str, name: str) -> Optional[HookDecl]:
        """Búsqueda O(1) del hook de un tipo — lo que consultará la Semántica."""
        return self.by_key.get((owner, name))

    def hooks_of(self, owner: str) -> Tuple[HookDecl, ...]:
        return tuple(h for h in self.hooks if h.owner == owner)

    @property
    def names(self) -> Tuple[str, ...]:
        """Vocabulario aportado por el usuario, sin repetir y ordenado."""
        return tuple(sorted({h.name for h in self.hooks}))

    def is_empty(self) -> bool:
        return not self.hooks and not self.modules

    # ------------------------------------------------------------------ #
    # serialización (CLI '--emit-extensions', tests, futuro caché)
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict:
        return {
            "project": self.project,
            "root": self.root,
            "manifest": self.manifest.path if self.manifest else None,
            "logic_dir": self.logic_dir,
            "calls_dir": self.calls_dir,
            "modules": [m.to_dict() for m in self.modules],
            "hooks": [
                {"name": h.name, "owner": h.owner, "params": list(h.params),
                 "returns": h.returns, "logic": h.logic, "module": h.module,
                 "file": h.file, "line": h.line, "column": h.column}
                for h in self.hooks
            ],
        }

    def config_entries(self) -> List[dict]:
        """La lista ``extensions:`` tal como se escribe en el yaml.

        Es la forma que el usuario puede copiar a mano en su
        ``.suriaX_config.yaml``; las rutas van RELATIVAS a la raíz para que el
        archivo siga siendo portable entre máquinas.
        """
        entries: List[dict] = []
        for module in self.modules:
            entry = {"path": os.path.relpath(module.path, self.root)}
            logic = sorted({h.logic for h in module.hooks if h.logic})
            if logic:
                entry["logic"] = logic
            entries.append(entry)
        return entries


def _python_files(folder: str) -> List[str]:
    """``.py`` de un directorio, recursivo y en orden determinista.

    Se ignoran los que empiezan por ``_`` (``__init__.py``, helpers privados):
    un archivo de declaraciones es público por definición.
    """
    found: List[str] = []
    for current, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS and not d.startswith("."))
        for name in sorted(files):
            if name.endswith(".py") and not name.startswith("_"):
                found.append(os.path.join(current, name))
    return found


def _config_paths(root: str, entries: Sequence) -> Tuple[List[str], List[ExtensionError]]:
    """Rutas de la lista ``extensions:`` del yaml.

    Acepta ``- path: plugins/physics.py`` y la forma corta
    ``- plugins/physics.py``: el yaml lo escribe una persona.
    """
    paths: List[str] = []
    errors: List[ExtensionError] = []
    for entry in entries or ():
        raw = entry.get("path") if isinstance(entry, dict) else entry
        if not isinstance(raw, str) or not raw.strip():
            errors.append(ExtensionError(
                EXT010, f"entrada de 'extensions' sin ruta utilizable: {entry!r}"))
            continue
        full = os.path.normpath(os.path.join(root, os.path.expanduser(raw)))
        if not os.path.isfile(full):
            errors.append(ExtensionError(
                EXT010, f"la extensión configurada no existe: {raw}"))
            continue
        paths.append(full)
    return paths, errors


def build(root: str, *, config_entries: Sequence = (), config_project: str = ""
          ) -> Tuple[Optional[ExtensionSet], List[ExtensionError]]:
    """Construye el ``ExtensionSet`` de un proyecto.

    Devuelve ``(None, [])`` cuando el proyecto no tiene extensiones — ni
    manifiesto ni entradas en el yaml. Es el camino silencioso y el caso
    normal de cualquier proyecto de hoy.

    Con errores devuelve ``(None, errores)``: un conjunto de extensiones a
    medias es peor que ninguno, porque la Semántica lo tomaría como el
    vocabulario completo y culparía al ``.srcx`` de lo que falta.
    """
    root = os.path.abspath(root)
    man, errors = manifest_mod.parse(root)
    if errors:
        return None, errors

    paths: List[str] = []
    if man is not None:
        paths.extend(_python_files(man.calls_dir))

    config_paths, config_errors = _config_paths(root, config_entries)
    errors.extend(config_errors)
    seen = {os.path.realpath(p) for p in paths}
    for path in config_paths:  # el yaml puede repetir lo que ya trae calls_dir
        if os.path.realpath(path) not in seen:
            seen.add(os.path.realpath(path))
            paths.append(path)

    if man is None and not paths:
        return None, errors

    declared_project, decls, scan_errors = scan_files(paths)
    errors.extend(scan_errors)
    if errors:
        return None, errors

    by_module: Dict[str, List[HookDecl]] = {}
    for decl in decls:
        by_module.setdefault(decl.file, []).append(decl)

    modules = tuple(
        ExtensionModule(
            name=os.path.splitext(os.path.basename(path))[0],
            path=path,
            hooks=tuple(by_module.get(path, ())),
        )
        for path in paths
    )

    # El nombre del proyecto lo DECLARA la extensión ('PROJECT' en el .py),
    # no el nombre de los archivos ni la carpeta. El manifiesto es el respaldo
    # cuando no hay .py que lo declare, y el yaml el último recurso (proyectos
    # sin extensiones). Ver 'readme.md' secc. "Nombre del proyecto".
    project = declared_project or (man.project if man else "") or config_project

    return ExtensionSet(
        root=root,
        project=project,
        manifest=man,
        logic_dir=man.logic_dir if man else None,
        calls_dir=man.calls_dir if man else None,
        modules=modules,
        hooks=tuple(decls),
        by_key={d.key: d for d in decls},
    ), []


__all__ = ["ExtensionModule", "ExtensionSet", "build"]
