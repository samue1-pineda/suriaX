"""Configuracion y verificacion de dependencias del compilador suriaX.

Responsabilidades:

 - **deteccion de plataforma** (Windows / Linux / web-playground);
 - **verificacion de dependencias** del core (LLVM-22, protobuf, pybind11,
   pyyaml) con mensajes claros y, si falta algo, aborto controlado;
 - **deteccion robusta de LLVM-22** via ``llvm-config`` (con fallback a
   ``LLVM_PATH`` / rutas estandar);
 - **formato de compilacion** en ``.suriaX_config.yaml``: generacion del
   archivo por defecto y su carga (``reload_config``).

Nota de filosofia: el usuario final no necesita estas dependencias; el binario
distribuido las trae resueltas. Esto importa al construir/ejecutar el
compilador desde el codigo fuente. Ver ``how_to_run.md``.
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

Algunas funciones, flags y metodos no deben activarse si ``IS_WEB`` es verdadero
(p. ej. el acceso al sistema de archivos local o la invocacion de toolchains
nativos). En la build del playground este flag pasa a ``True`` y el target por
defecto es ``wasm`` (LLVM IR -> WebAssembly).
"""

# version de LLVM requerida por el proyecto.
REQUIRED_LLVM_MAJOR = 22

_config_fname = ".suriaX_config.yaml"


# --------------------------------------------------------------------------- #
# dependencias
# --------------------------------------------------------------------------- #
class DependencyError(RuntimeError):
    """Una dependencia obligatoria del compilador no esta disponible."""


def _check_python_module(module: str) -> Optional[str]:
    """Devuelve la version del modulo si esta instalado, o ``None`` si falta."""
    try:
        mod = __import__(module)
    except ImportError:
        return None
    return getattr(mod, "__version__", "desconocida")


def find_llvm_config() -> Optional[str]:
    """Localiza el ejecutable ``llvm-config`` (preferentemente el de la versión
    requerida).

    Orden de busqueda:
      1. ``LLVM_PATH``/bin/llvm-config (si la env var esta definida);
      2. ``llvm-config-<REQUIRED_LLVM_MAJOR>`` en el PATH (hoy ``llvm-config-22``);
      3. ``llvm-config`` generico en el PATH.
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
    """Devuelve la version completa de LLVM detectada (p. ej. ``21.1.0``).

    Usa ``llvm-config --version`` como fuente de verdad. Devuelve ``None`` si no
    se encuentra ``llvm-config`` o si falla la consulta.
    """
    cfg = find_llvm_config()
    if cfg is None:
        return None
    try:
        out = subprocess.run(
            [cfg, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    version = out.stdout.strip()
    return version or None


def _llvm_status() -> tuple[bool, str]:
    """(ok, detalle) sobre la disponibilidad de LLVM (version requerida)."""
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
    """Verifica las dependencias y **aborta** con un mensaje claro si falta alguna.

    :param required: subconjunto de dependencias a exigir (por nombre pip:
        ``llvm``, ``protobuf``, ``pybind11``, ``pyyaml``). Si es ``None`` se
        exigen todas. Util para fases que no necesitan todo el toolchain (p. ej.
        el lexer no necesita LLVM).
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
# rutas de LLVM (para el backend / bindings)
# --------------------------------------------------------------------------- #
def default_llvm_include_path() -> str:
    """Mejor estimacion de la ruta de headers de LLVM segun la plataforma."""
    llvm_path = os.environ.get("LLVM_PATH")
    if llvm_path:
        return os.path.join(llvm_path, "include")

    cfg = find_llvm_config()
    if cfg is not None:
        try:
            out = subprocess.run(
                [cfg, "--includedir"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
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


# --------------------------------------------------------------------------- #
# formato de compilacion (.suriaX_config.yaml)
# --------------------------------------------------------------------------- #
def _detect_target_triple() -> str:
    """Mejor estimacion del target-triple via ``llvm-config --host-target``."""
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


def _default_artifact() -> str:
    """Extension del artefacto del backend segun la plataforma/target."""
    if IS_WEB:
        return "wasm"
    if IS_WIN32:
        return "exe"
    return "o"  # Linux/otros: objeto, luego enlazado por el linker


def _detect_linker() -> str:
    """Mejor estimacion del linker del sistema (vacio si no se detecta)."""
    if IS_WEB:
        return "wasm-ld"
    for name in ("ld.lld", "lld", "ld", "link" if IS_WIN32 else "ld"):
        found = shutil.which(name)
        if found:
            return found
    return ""


def _default_config() -> dict:
    """Esquema del formato de compilacion con la informacion que el backend
    necesita para compilar de verdad: toolchain, target, visualizacion y
    busqueda de librerias.
    """
    return {
        "version": 1,
        "target": "wasm" if IS_WEB else "native",  # native | wasm
        "platform": (
            "win32" if IS_WIN32 else "linux" if IS_LINUX else
            "macos" if IS_MACOS else sys.platform
        ),
        "optimization": "O0",  # O0 | O1 | O2 | O3

        # --- toolchain: rutas que el backend C++ usa para compilar/enlazar ---
        "toolchain": {
            "llvm_required_major": REQUIRED_LLVM_MAJOR,
            "llvm_path": os.environ.get("LLVM_PATH", ""),
            "llvm_config": find_llvm_config() or "",
            "llvm_include": default_llvm_include_path(),
            "linker": _detect_linker(),
            "sysroot": os.environ.get("SURIAX_SYSROOT", ""),
        },

        # --- target detallado: triple/arch/artefacto + opciones wASM ---
        "codegen": {
            "triple": _detect_target_triple(),
            "arch": platform.machine(),
            "artifact": _default_artifact(),   # o | exe | wasm
            "wasm": {
                "enabled": IS_WEB,
                "stack_size": 1048576,
                "export_all": False,
            },
        },

        # --- visualizacion: que etapas volcar (objetivo educativo) ---
        "visualization": {
            "stages": [],        # p.ej. ["tokens", "ast", "hir", "mir", "llvm-ir"]
            "format": "text",    # text | json | dot
            "output_dir": "viz",
        },

        # --- librerias: busqueda de .libsrx y bindings C++ ---
        "libraries": {
            "libsrx_paths": ["./lib", "./libsrx"],
            "extern_cpp_include": [],   # headers C++ para '#extern cpp{}'
            "bindings": [],             # modulos pybind11 a enlazar
        },

        "paths": {
            "input": "",
            "output": "out",
        },
        "flags": {
            "is_web": IS_WEB,
        },
    }


def generate_config(path: Optional[str] = None, *, overwrite: bool = False) -> str:
    """Genera el ``.suriaX_config.yaml`` por defecto y devuelve su ruta.

    No sobreescribe un archivo existente salvo ``overwrite=True``.
    """
    import yaml  # local: pyyaml es una dependencia verificada aparte

    target = path or os.path.join(os.getcwd(), _config_fname)
    if os.path.exists(target) and not overwrite:
        return target

    with open(target, "w", encoding="utf-8") as fh:
        yaml.safe_dump(_default_config(), fh, sort_keys=False, allow_unicode=True)
    return target


def reload_config(path: Optional[str] = None) -> dict:
    """Carga el formato de compilacion desde ``.suriaX_config.yaml``.

    Si el archivo no existe, devuelve la configuracion por defecto (sin
    escribir nada en disco).
    """
    import yaml

    target = path or os.path.join(os.getcwd(), _config_fname)
    if not os.path.isfile(target):
        return _default_config()
    with open(target, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    # mezcla superficial sobre los defaults para tolerar archivos parciales.
    config = _default_config()
    config.update(data)
    return config


# --------------------------------------------------------------------------- #
# parseo de artefactos por plataforma (stubs, backend futuro)
# --------------------------------------------------------------------------- #
def _parse_linux(source):
    """parse Linux .o"""


def _parse_win(source):
    """parse windows .exe"""


def _parse_web(source):
    """parse playground wASM"""


# --------------------------------------------------------------------------- #
# diagnostico por linea de comandos:  python compilerconfig.py
# --------------------------------------------------------------------------- #
def _print_report() -> int:
    print("suriaX - verificacion de dependencias\n")
    report = check_dependencies()
    all_ok = True
    for name, info in report.items():
        mark = "OK " if info["ok"] else "FALTA"
        print(f"  [{mark}] {name}: {info['detail']}")
        if not info["ok"]:
            all_ok = False
            print(f"          -> {info['install']}")
    print("\nplataforma:", "web" if IS_WEB else _default_config()["platform"])
    print("target por defecto:", _default_config()["target"])
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(_print_report())
