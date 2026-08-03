"""ORQUESTADOR del paquete ``config/`` (refactorización de ``V0/compilerconfig.py``).

Un solo punto de importación para el resto del compilador — mantiene la API
histórica (``import compilerconfig`` desde ``V0/main.py`` sigue funcionando
tras el cambio de ruta) mientras cada responsabilidad vive en su módulo:

    dependencies.py   plataforma + verificación de dependencias + LLVM
    yaml_config.py    esquema/generación/carga de .suriaX_config.yaml
                      + resolución de rutas relativa a la raíz del proyecto
    logs.py           generador de logs (./log: JSONL + espejo legible)
    dumps.py          volcados: AST .json y tokens .txt (./dumps)
    cache.py          verificador de caché de build (./build/cache,
                      entrada al runtime system y a suriniX)

Diagnóstico por línea de comandos:  ``python -m config.compilerconfig``
"""

from __future__ import annotations

# --- plataforma y dependencias --------------------------------------------- #
from .dependencies import (
    IS_LINUX,
    IS_MACOS,
    IS_WEB,
    IS_WIN32,
    REQUIRED_LLVM_MAJOR,
    DependencyError,
    check_dependencies,
    default_llvm_include_path,
    detect_llvm_version,
    ensure_dependencies,
    find_llvm_config,
)

# --- formato de compilación (.suriaX_config.yaml) --------------------------- #
from .yaml_config import (
    CONFIG_FNAME,
    default_config,
    generate_config,
    project_root,
    reload_config,
    resolve_path,
)

# --- salidas: logs / volcados / caché --------------------------------------- #
from .logs import CompilerLog
from .debug_report import DebugReport
from .dumps import dump_ast_json, dump_hir, dump_tokens_txt, dumps_dir
from .cache import ensure_cache_dir, verify_cache

# compat: nombre interno historico usado por V0/main.py
_default_config = default_config
_config_fname = CONFIG_FNAME


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
# diagnóstico por línea de comandos
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
    config = default_config()
    print("\nplataforma:", "web" if IS_WEB else config["platform"])
    print("target por defecto:", config["target"])
    print("rutas .libsrx por defecto:", ", ".join(config["libraries"]["libsrx_paths"]))
    cache_report = verify_cache(reload_config())
    print(f"cache: {cache_report['dir']}  "
          f"({cache_report['fresh']} vigentes, {cache_report['pruned']} podadas)")
    return 0 if all_ok else 1


__all__ = [
    # dependencias / plataforma
    "IS_WIN32", "IS_LINUX", "IS_MACOS", "IS_WEB", "REQUIRED_LLVM_MAJOR",
    "DependencyError", "check_dependencies", "ensure_dependencies",
    "find_llvm_config", "detect_llvm_version", "default_llvm_include_path",
    # configuración
    "CONFIG_FNAME", "default_config", "generate_config", "reload_config",
    "project_root", "resolve_path",
    # salidas
    "CompilerLog", "DebugReport",
    "dump_ast_json", "dump_hir", "dump_tokens_txt", "dumps_dir",
    "ensure_cache_dir", "verify_cache",
]


if __name__ == "__main__":
    raise SystemExit(_print_report())
