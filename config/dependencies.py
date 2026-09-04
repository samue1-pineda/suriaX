"""Detección de plataforma y verificación de dependencias del compilador.

Módulo del paquete ``config/`` (ver ``config/readme.md``). Responsabilidades:

 - **detección de plataforma** (Windows / Linux / macOS / web-playground);
 - **verificación de dependencias** del core (protobuf, pybind11, pyyaml)
   con mensajes claros y, si falta algo, aborto controlado;
 - **estimación de toolchain** (triple, linker, artefacto) que consume
   ``yaml_config.py``.

LLVM ya NO se detecta: el target nativo es la VM de bytecode con JIT y LLVM
no está en la ruta de generación de código (ver ``ARCHITECTURE.md``).
Comprobar una dependencia que nada usa solo servía para que ``--check``
saliera en rojo en una máquina perfectamente capaz de compilar.

Nota de filosofía: el usuario final no necesita estas dependencias; el
binario distribuido las trae resueltas. Esto importa al construir/ejecutar
el compilador desde el código fuente. Ver ``how_to_run.md``.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from typing import Optional

# --------------------------------------------------------------------------- #
# plataforma
# --------------------------------------------------------------------------- #
IS_WIN32 = sys.platform.startswith("win32")
IS_LINUX = sys.platform.startswith("linux")
IS_MACOS = sys.platform.startswith("darwin")

IS_WEB = False
"""Modo playground (target wASM).

Algunas funciones, flags y métodos no deben activarse si ``IS_WEB`` es
verdadero (p. ej. el acceso al sistema de archivos local o la invocación de
toolchains nativos). En la build del playground este flag pasa a ``True`` y
el target por defecto es ``wasm``.
"""


# --------------------------------------------------------------------------- #
# dependencias
# --------------------------------------------------------------------------- #
class DependencyError(RuntimeError):
    """Una dependencia obligatoria del compilador no está disponible."""


def _check_python_module(module: str) -> Optional[str]:
    """Devuelve la versión del módulo si está instalado, o ``None`` si falta."""
    try:
        mod = __import__(module)
    except ImportError:
        return None
    return getattr(mod, "__version__", "desconocida")


def check_dependencies() -> dict[str, dict]:
    """Verifica todas las dependencias del core y devuelve un reporte.

    El reporte es ``{nombre: {"ok": bool, "detail": str, "install": str}}``.
    No aborta: solo informa. Para abortar usar :func:`ensure_dependencies`.
    """
    report: dict[str, dict] = {}

    for mod, pip_name in (
        ("google.protobuf", "protobuf"),
        ("pybind11", "pybind11"),
        ("yaml", "pyyaml"),
    ):
        version = _check_python_module(mod)
        report[pip_name] = {
            "ok": version is not None,
            "detail": f"version {version}" if version else "no instalado",
            "install": f"pip install {pip_name}  (o: pip install -r requirements.txt)",
        }

    return report


def ensure_dependencies(*, required: Optional[set[str]] = None) -> None:
    """Verifica las dependencias y **aborta** con mensaje claro si falta alguna.

    :param required: subconjunto a exigir (por nombre pip: ``protobuf``,
        ``pybind11``, ``pyyaml``). ``None`` = todas. Útil para las fases que
        no necesitan todo (el frontend solo necesita la librería estándar).
    """
    report = check_dependencies()
    if required is not None:
        report = {k: v for k, v in report.items() if k in required}

    missing = {k: v for k, v in report.items() if not v["ok"]}
    if not missing:
        return

    lines = ["faltan dependencias necesarias para esta operacion:\n"]
    for name, info in missing.items():
        lines.append(f"  - {name}: {info['detail']}")
        lines.append(f"      -> {info['install']}")
    lines.append("\nver how_to_run.md para mas detalles.")
    raise DependencyError("\n".join(lines))


# --------------------------------------------------------------------------- #
# rutas y estimaciones de toolchain (consumidas por yaml_config.py)
# --------------------------------------------------------------------------- #
def detect_target_triple() -> str:
    """Mejor estimación del target-triple de la máquina actual.

    Se deduce de la plataforma y la arquitectura, sin preguntarle a ningún
    toolchain externo: el triple solo describe para qué máquina se compila, y
    arrancar un subproceso para averiguarlo era el único motivo por el que
    cargar la configuración tocaba el disco fuera del proyecto.
    """
    if IS_WEB:
        return "wasm32-unknown-unknown"
    if IS_WIN32:
        return "x86_64-pc-windows-msvc"
    if IS_MACOS:
        return "arm64-apple-darwin"
    return "x86_64-unknown-linux-gnu"


def default_artifact() -> str:
    """Extensión del artefacto del backend según la plataforma/target."""
    if IS_WEB:
        return "wasm"
    if IS_WIN32:
        return "exe"
    return "o"  # Linux/otros: objeto, luego enlazado por el linker


def detect_linker() -> str:
    """Mejor estimación del linker del sistema (vacío si no se detecta)."""
    if IS_WEB:
        return "wasm-ld"
    for name in ("ld.lld", "lld", "ld", "link" if IS_WIN32 else "ld"):
        found = shutil.which(name)
        if found:
            return found
    return ""


def detect_cxx() -> str:
    """El compilador de C++ del sistema, o ``""``.

    ``#extern cpp`` se compila con ESTO y con nada más: el usuario no tiene
    que traer un sistema de build. Se respeta ``CXX`` como en cualquier
    proyecto de C++, y si no está se prueban los dos habituales.
    """
    desde_entorno = os.environ.get("CXX")
    if desde_entorno:
        return shutil.which(desde_entorno) or ""
    for name in ("g++", "clang++"):
        found = shutil.which(name)
        if found:
            return found
    return ""


def detect_cc() -> str:
    """El compilador de C del sistema, o ``""`` (espejo de :func:`detect_cxx`)."""
    desde_entorno = os.environ.get("CC")
    if desde_entorno:
        return shutil.which(desde_entorno) or ""
    for name in ("gcc", "clang", "cc"):
        found = shutil.which(name)
        if found:
            return found
    return ""


def machine_arch() -> str:
    return platform.machine()


__all__ = [
    "IS_WIN32", "IS_LINUX", "IS_MACOS", "IS_WEB",
    "DependencyError", "check_dependencies", "ensure_dependencies",
    "detect_target_triple", "default_artifact", "detect_linker", "machine_arch",
    "detect_cxx", "detect_cc",
]
