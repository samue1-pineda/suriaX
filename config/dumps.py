"""Generadores de volcados del compilador (``./dumps``).

Módulo del paquete ``config/``. Todo artefacto de inspección va a la
carpeta de volcados (``output.dumps_dir`` del yaml, por defecto
``./dumps`` en la raíz del proyecto) en lugar de mezclarse con el fuente:

 - **AST-tipado a JSON** (``<fuente>.ast.json``): la misma representación
   de ``#test ast``/``#test sem``, ya anotada por la Semántica (``restype``,
   hooks enlazados).
 - **volcado de tokens a texto** (``<fuente>.tokens.txt``): el arreglo
   completo de tokens en el formato de ``#test lexer``, un token por línea.

Este módulo NO conoce el AST ni los tokens en detalle: recibe los objetos y
delega la serialización en ``include/ast_json.py`` (reflexión cacheada) y en
``Token.__repr__``. Así añadir un volcado nuevo (HIR, MIR...) es añadir una
función aquí, sin tocar el frontend.
"""

from __future__ import annotations

import os
from typing import List, Optional

from .yaml_config import resolve_path


def dumps_dir(config: Optional[dict]) -> str:
    """Carpeta de volcados según la config (creada bajo demanda)."""
    output_cfg = (config or {}).get("output") or {}
    return resolve_path(config, output_cfg.get("dumps_dir", "./dumps"))


def _target_path(config: Optional[dict], source_path: str, suffix: str,
                 explicit: Optional[str]) -> str:
    """Ruta final de un volcado: explícita del usuario, o
    ``<dumps_dir>/<basename del fuente><suffix>``.

    En los DOS casos se crea la carpeta destino. La ruta explícita no la
    creaba, y eso rompía el caso normal de un clon recién hecho: ``dumps/``
    no se versiona, así que compilar con ``--emit-hir <ruta>`` un programa
    que importa una librería reventaba con un ``FileNotFoundError`` sin
    diagnóstico —el emisor de unidades pasa una ruta explícita dentro de
    ``dumps/``— en vez de escribir el volcado. Quien elige la ruta no tiene
    por qué haber creado el directorio.
    """
    if explicit:
        directory = os.path.dirname(os.path.abspath(explicit))
        if directory:
            os.makedirs(directory, exist_ok=True)
        return explicit
    base = os.path.basename(source_path)
    directory = dumps_dir(config)
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, base + suffix)


def dump_ast_json(program, *, source_path: str, config: Optional[dict] = None,
                  out_path: Optional[str] = None) -> str:
    """Vuelca el AST(-tipado) a JSON y devuelve la ruta escrita."""
    # import diferido: config/ no debe cargar el frontend salvo que se use
    import sys
    v0_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "V0")
    if v0_root not in sys.path:  # pragma: no cover - main.py ya lo inserta
        sys.path.insert(0, v0_root)
    from V0.include.ast_json import to_json

    target = _target_path(config, source_path, ".ast.json", out_path)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(to_json(program))
        fh.write("\n")
    return target


def _escribe_entero(destino: str, datos: bytes) -> None:
    """Escribe ``datos`` en ``destino`` de modo que nadie lo lea a medias.

    Dos compilaciones en la misma carpeta (``make -j``, el editor y una
    terminal a la vez) escriben los MISMOS ``.phir`` de librería en
    ``dumps/``. Con ``open(..., "wb")`` el archivo se vaciaba primero, y la
    otra podía leerlo vacío o cortado: un ``schema_version 0`` y un fallo
    interno. Aquí se escribe en un temporal de la misma carpeta y se cambia
    de nombre de una vez, que el sistema hace atómico.

    En Windows el cambio de nombre falla mientras otro proceso tiene el
    destino abierto; como el contenido es el mismo (el HIR es
    reproducible), se reintenta un momento y, si sigue abierto, se deja el
    que ya hay.
    """
    import tempfile
    import time

    carpeta = os.path.dirname(os.path.abspath(destino))
    fd, temporal = tempfile.mkstemp(dir=carpeta, prefix=".phir-",
                                    suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(datos)
        for intento in range(20):
            try:
                os.replace(temporal, destino)
                return
            except PermissionError:
                if intento == 19:
                    raise
                time.sleep(0.05)
    except PermissionError:
        if os.path.isfile(destino):
            with open(destino, "rb") as fh:
                if fh.read() == datos:
                    return
        raise
    finally:
        if os.path.exists(temporal):
            os.remove(temporal)


def dump_hir(data: bytes, *, source_path: str, config: Optional[dict] = None,
             out_path: Optional[str] = None,
             text: Optional[str] = None) -> str:
    """Vuelca el HIR serializado (protobuf, ``bytes``) a ``<fuente>.phir``
    (**p**roto**hir**), el artefacto que cruza la frontera hacia los targets
    (MIR/C++ e intérprete).

    Si se pasa ``text`` (el mismo ``Module`` en formato de TEXTO de
    protobuf), se escribe junto al binario como ``<fuente>.phir.txt`` —
    debugging del formato sin herramientas extra (mismo contenido que
    ``#test hir``).
    """
    target = _target_path(config, source_path, ".phir", out_path)
    _escribe_entero(target, data)
    if text is not None:
        with open(target + ".txt", "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.write("\n")
    return target


def hir_pretty_path(*, source_path: str, config: Optional[dict] = None,
                    out_path: Optional[str] = None) -> str:
    """Ruta de la vista LEGIBLE del HIR (``<fuente>.phir.pretty``).

    Devuelve la ruta en vez de escribir el contenido, a diferencia del resto
    de volcados: la vista se escribe en STREAMING (``HIR/pretty.write_pretty``)
    porque para un programa grande son megabytes que no tiene sentido armar en
    memoria. Aquí vive la política de dónde va; el contenido lo pone el
    paquete HIR, que es quien conoce el formato.
    """
    return _target_path(config, source_path, ".phir.pretty", out_path)


def dump_tokens_txt(tokens: List, *, source_path: str, config: Optional[dict] = None,
                    out_path: Optional[str] = None) -> str:
    """Vuelca la lista de tokens a un ``.txt`` y devuelve la ruta escrita.

    Mismo formato que ``#test lexer`` (``[idx] Token(...)`` por línea):
    la salida es comparable 1:1 con lo que el usuario ve en consola.
    """
    target = _target_path(config, source_path, ".tokens.txt", out_path)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(f"=== tokens ({len(tokens)}) — {source_path} ===\n")
        for i, tok in enumerate(tokens):
            fh.write(f"[{i:>4}] {tok!r}\n")
    return target


__all__ = ["dumps_dir", "dump_ast_json", "dump_hir", "dump_tokens_txt",
           "hir_pretty_path"]
