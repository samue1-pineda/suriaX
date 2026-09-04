"""HTIMS — *hooks / traits / intrinsics management system*.

La capa que corre **antes del análisis léxico** y responde a una sola
pregunta: ¿este proyecto extiende el lenguaje, y con qué? Si la respuesta es
"no" (el caso de todo proyecto de hoy) no cuesta más que un ``stat`` y no
emite un solo diagnóstico.

Su razón de ser: que los hooks dejen de ser funciones especiales **creadas
por el compilador** y pasen a ser vocabulario que **declara el usuario**. El
manifiesto ``extends.srcx`` dice dónde vive esa declaración (``calls_dir``,
Python) y dónde vivirá su lógica (``logic_dir``, C++, cuando exista la
VM+JIT).

Frontera (por diseño, ver ``readme.md``):

  - no importa NADA de ``V0/`` ni de ``src/`` — sobrevive a un rediseño del
    frontend, y el frontend compila igual sin este paquete;
  - nunca importa ni ejecuta el ``.py`` del usuario: lo lee con ``ast.parse``;
  - el backend **web no lo conoce ni lo llama**: los campos que el HIR gana
    son aditivos y su decodificador salta lo que no conoce.

Uso desde el compilador::

    from htims import discover
    extensions, errors = discover(config)   # config trae '_root'

Uso desde un test o una herramienta, sin config::

    from htims import build
    extensions, errors = build("/ruta/al/proyecto")
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .declarations import HookDecl, scan_file, scan_files
from .decl import HookSpec, hook, signature, signature_extends
from .errors import ExtensionError, Location
from .manifest import MANIFEST_FNAME, Manifest
from .registry import ExtensionModule, ExtensionSet, build

#: clave donde el ``ExtensionSet`` viaja dentro de la configuración cargada.
#: El guion bajo sigue la convención de ``_root``: valor RESUELTO en memoria,
#: no parte del yaml que el usuario escribe.
CONFIG_KEY = "_extensions"


def discover(config: dict) -> Tuple[Optional[ExtensionSet], List[ExtensionError]]:
    """Descubre las extensiones del proyecto descrito por ``config``.

    Lee la raíz de ``config['_root']`` (la que ya calcula
    ``config/yaml_config``) y la lista ``extensions:`` del yaml. Al terminar
    deja en ``config``:

      - ``_extensions``: el :class:`ExtensionSet` (o ``None``);
      - ``project``: el nombre declarado, si la extensión declara uno;
      - ``extensions``: la lista materializada, para que ``--emit-extensions``
        muestre exactamente lo que el usuario puede copiar a su yaml.

    **No escribe nada en disco.** El ``.suriaX_config.yaml`` del usuario es
    suyo; el compilador lo lee y lo completa en memoria.
    """
    root = config.get("_root")
    if not root:
        return None, []

    extensions, errors = build(
        root,
        config_entries=config.get("extensions") or (),
        config_project=config.get("project") or "",
    )
    config[CONFIG_KEY] = extensions
    if extensions is not None:
        if extensions.project:
            config["project"] = extensions.project
        config["extensions"] = extensions.config_entries()
    return extensions, errors


def of(config: dict) -> Optional[ExtensionSet]:
    """El ``ExtensionSet`` ya descubierto de una configuración, o ``None``.

    Para las fases que solo quieren consultarlo sin volver a descubrir nada.
    """
    return config.get(CONFIG_KEY)


__all__ = [
    "CONFIG_KEY", "MANIFEST_FNAME",
    "ExtensionError", "ExtensionModule", "ExtensionSet", "HookDecl",
    "HookSpec", "Location", "Manifest",
    "build", "discover", "hook", "of", "scan_file", "scan_files",
    "signature", "signature_extends",
]
