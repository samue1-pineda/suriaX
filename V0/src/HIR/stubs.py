"""Stubs protobuf del HIR: generación EN BUILD y carga perezosa.

Los ``hir_pb2.py`` generados **no se commitean** (PROTOBUF_BRIDGE.md secc.
2): se producen con ``protoc`` a partir de ``proto/hir.proto`` dentro de
``gen/`` (ignorada por git) cuando faltan o el ``.proto`` es más nuevo que
el stub (comparación de mtime — un ``stat``, costo despreciable frente a
re-generar siempre).

Este módulo NO importa ``google.protobuf`` en el nivel superior: el frontend
completo (lexer → semántica) sigue funcionando sin la dependencia instalada;
solo la fase HIR la exige, vía :func:`load_hir_pb2`.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from types import ModuleType

_HIR_DIR = os.path.dirname(os.path.abspath(__file__))
_PROTO_DIR = os.path.join(_HIR_DIR, "proto")
_PROTO_FILE = os.path.join(_PROTO_DIR, "hir.proto")
_GEN_DIR = os.path.join(_HIR_DIR, "gen")
_STUB_FILE = os.path.join(_GEN_DIR, "hir_pb2.py")

# cache de proceso: el modulo generado se ejecuta UNA sola vez por corrida
_loaded: ModuleType | None = None


class StubGenerationError(RuntimeError):
    """No fue posible generar o cargar los stubs protobuf del HIR."""


def _stub_is_stale() -> bool:
    try:
        return os.path.getmtime(_STUB_FILE) < os.path.getmtime(_PROTO_FILE)
    except OSError:  # el stub no existe todavia
        return True


def _generate_stub() -> None:
    protoc = shutil.which("protoc")
    if protoc is None:
        raise StubGenerationError(
            "no se encontró 'protoc' (compilador de protobuf), necesario para "
            "generar los stubs del HIR.\n"
            "  -> instálalo con tu gestor de paquetes (apt/pacman/brew: protobuf)"
        )
    os.makedirs(_GEN_DIR, exist_ok=True)
    result = subprocess.run(
        [protoc, f"--proto_path={_PROTO_DIR}", f"--python_out={_GEN_DIR}", _PROTO_FILE],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise StubGenerationError(
            f"protoc no pudo compilar {_PROTO_FILE}:\n{result.stderr.strip()}"
        )


def load_hir_pb2() -> ModuleType:
    """Devuelve el módulo ``hir_pb2`` generado, regenerándolo si hace falta.

    Lanza :class:`StubGenerationError` si falta ``protoc`` o el runtime
    ``google.protobuf`` (el mensaje incluye cómo instalarlo); el llamador
    (``V0/main.py``) lo reporta como error de dependencia de la fase HIR.
    """
    global _loaded
    if _loaded is not None:
        return _loaded

    # este modulo puede importarse bajo DOS nombres de paquete distintos
    # ('src.HIR.stubs' desde V0/main.py, 'V0.src.HIR.stubs' desde el
    # interprete): cada instancia tiene su propio '_loaded', pero el stub
    # generado solo puede ejecutarse UNA vez por proceso (el descriptor
    # pool de protobuf es global y rechaza archivos duplicados).
    existing = sys.modules.get("suriax_hir_pb2")
    if existing is not None:
        _loaded = existing
        return existing

    if importlib.util.find_spec("google.protobuf") is None:
        raise StubGenerationError(
            "falta el runtime de protobuf para Python ('google.protobuf').\n"
            "  -> pip install protobuf  (o python-protobuf con tu gestor de paquetes)"
        )

    if _stub_is_stale():
        _generate_stub()

    spec = importlib.util.spec_from_file_location("suriax_hir_pb2", _STUB_FILE)
    if spec is None or spec.loader is None:  # pragma: no cover - stub recien generado
        raise StubGenerationError(f"no se pudo cargar el stub generado: {_STUB_FILE}")
    module = importlib.util.module_from_spec(spec)
    # registrado en sys.modules ANTES de exec: el propio stub se auto-refiere
    # via el registry de descriptores de protobuf.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _loaded = module
    return module


__all__ = ["load_hir_pb2", "StubGenerationError"]
