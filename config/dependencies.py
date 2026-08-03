"""Detección de plataforma y verificación de dependencias del compilador.

Módulo del paquete ``config/`` (ver ``config/readme.md``). Responsabilidades:

 - **detección de plataforma** (Windows / Linux / macOS / web-playground);
 - **verificación de dependencias** del core (LLVM-22, protobuf, pybind11,
   pyyaml) con mensajes claros y, si falta algo, aborto controlado;
 - **detección robusta de LLVM-22** via ``llvm-config`` (con fallback a
   ``LLVM_PATH`` / rutas estándar) y estimación de toolchain (triple,
   linker, artefacto) que consume ``yaml_config.py``.

Nota de filosofía: el usuario final no necesita estas dependencias; el
binario distribuido las trae resueltas. Esto importa al construir/ejecutar
el compilador desde el código fuente. Ver ``how_to_run.md``.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
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
el target por defecto es ``wasm`` (LLVM IR -> WebAssembly).
"""

# versión de LLVM requerida por el proyecto.
REQUIRED_LLVM_MAJOR = 22


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


def find_llvm_config() -> Optional[str]:
    """Localiza el ejecutable ``llvm-config`` (preferentemente el de la
    versión requerida).

    Orden de búsqueda:
      1. ``LLVM_PATH``/bin/llvm-config (si la env var está definida);
      2. ``llvm-config-<REQUIRED_LLVM_MAJOR>`` en el PATH;
      3. ``llvm-config`` genérico en el PATH.
    """
    llvm_path = os.environ.get("LLVM_PATH")
    if llvm_path:
        candidate = os.path.join(
            llvm_path, "bin", "llvm-config.exe" if IS_WIN32 else "llvm-config"
        )
        if os.path.isfile(candidate):
            return candidate

    for name in (f"llvm-config-{REQUIRED_LLVM_MAJOR}", "llvm-config"):
        found = shutil.which(name)
        if found:
            return found
    return None


def detect_llvm_version() -> Optional[str]:
    """Versión completa de LLVM detectada (p. ej. ``22.1.0``) o ``None``.

    Usa ``llvm-config --version`` como fuente de verdad.
    """
    cfg = find_llvm_config()
    if cfg is None:
        return None
    try:
        out = subprocess.run(
            [cfg, "--version"],
            capture_output=True, text=True, timeout=10, check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    version = out.stdout.strip()
    return version or None


def _llvm_status() -> tuple[bool, str]:
    """(ok, detalle) sobre la disponibilidad de LLVM (versión requerida)."""
    version = detect_llvm_version()
    if version is None:
        return False, "no se encontro 'llvm-config' (LLVM no instalado o fuera del PATH)"
    match = re.match(r"(\d+)", version)
    major = int(match.group(1)) if match else -1
    if major != REQUIRED_LLVM_MAJOR:
        return False, f"se requiere LLVM {REQUIRED_LLVM_MAJOR}, detectado {version}"
    return True, version


def check_dependencies() -> dict[str, dict]:
    """Verifica todas las dependencias del core y devuelve un reporte.

    El reporte es ``{nombre: {"ok": bool, "detail": str, "install": str}}``.
    No aborta: solo informa. Para abortar usar :func:`ensure_dependencies`.
    """
    report: dict[str, dict] = {}

    llvm_ok, llvm_detail = _llvm_status()
    report["llvm"] = {
        "ok": llvm_ok,
        "detail": llvm_detail,
        "install": f"instala LLVM-{REQUIRED_LLVM_MAJOR} con tu gestor de "
        "paquetes (apt/pacman/brew) o define LLVM_PATH",
    }

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

    :param required: subconjunto a exigir (por nombre pip: ``llvm``,
        ``protobuf``, ``pybind11``, ``pyyaml``). ``None`` = todas. Útil para
        fases que no necesitan todo el toolchain (el frontend no necesita LLVM).
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
def default_llvm_include_path() -> str:
    """Mejor estimación de la ruta de headers de LLVM según la plataforma."""
    llvm_path = os.environ.get("LLVM_PATH")
    if llvm_path:
        return os.path.join(llvm_path, "include")

    cfg = find_llvm_config()
    if cfg is not None:
        try:
            out = subprocess.run(
                [cfg, "--includedir"],
                capture_output=True, text=True, timeout=10, check=True,
            )
            path = out.stdout.strip()
            if path:
                return path
        except (subprocess.SubprocessError, OSError):
            pass

    if IS_WIN32:
        return "llvm_include_not_found"
    if IS_MACOS:
        return os.path.join(os.sep, "opt", "homebrew", "opt", "llvm", "include")
    return os.path.join(os.sep, "usr", "lib", f"llvm-{REQUIRED_LLVM_MAJOR}", "include")


def detect_target_triple() -> str:
    """Mejor estimación del target-triple via ``llvm-config --host-target``."""
    if IS_WEB:
        return "wasm32-unknown-unknown"
    cfg = find_llvm_config()
    if cfg is not None:
        try:
            out = subprocess.run(
                [cfg, "--host-target"],
                capture_output=True, text=True, timeout=10, check=True,
            )
            triple = out.stdout.strip()
            if triple:
                return triple
        except (subprocess.SubprocessError, OSError):
            pass
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


def machine_arch() -> str:
    return platform.machine()


__all__ = [
    "IS_WIN32", "IS_LINUX", "IS_MACOS", "IS_WEB", "REQUIRED_LLVM_MAJOR",
    "DependencyError", "check_dependencies", "ensure_dependencies",
    "find_llvm_config", "detect_llvm_version", "default_llvm_include_path",
    "detect_target_triple", "default_artifact", "detect_linker", "machine_arch",
]
