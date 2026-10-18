"""ORQUESTADOR del paquete ``config/`` (refactorización de ``V0/compilerconfig.py``).

Un solo punto de importación para el resto del compilador — mantiene la API
histórica (``import compilerconfig`` desde ``V0/main.py`` sigue funcionando
tras el cambio de ruta) mientras cada responsabilidad vive en su módulo:

    dependencies.py   plataforma + verificación de dependencias
    errors.py         diagnósticos del formato (familia CFG0xx)
    validate.py       validación del .suriaX_config.yaml contra el esquema
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
    DependencyError,
    check_dependencies,
    ensure_dependencies,
)

# --- diagnósticos del formato de compilación ------------------------------- #
from .errors import ConfigError
from .validate import validate

# --- formato de compilación (.suriaX_config.yaml) --------------------------- #
from .yaml_config import (
    CONFIG_FNAME,
    ERRORS_KEY,
    default_config,
    errors_of,
    generate_config,
    project_root,
    reload_config,
    resolve_path,
)

# --- salidas: logs / volcados / caché --------------------------------------- #
from .logs import CompilerLog
from .debug_report import DebugReport
from .dumps import (dump_ast_json, dump_hir, dump_tokens_txt, dumps_dir,
                    hir_pretty_path)
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
def _print_extensions(config: dict) -> None:
    """Estado de la capa HTIMS: el manifiesto y las rutas que declara.

    ``--check`` respondía por las dependencias y por las rutas de librerías,
    pero callaba sobre las EXTENSIONES, que es la otra mitad de lo que define
    un proyecto: si ``extends.srcx`` no está donde el usuario cree, o declara
    un directorio que no existe, no había forma de verlo sin compilar algo.
    """
    import os

    from .yaml_config import project_root

    # importacion PEREZOSA a proposito: 'config/' no depende de 'htims/' —
    # solo lo consulta cuando alguien pide el reporte. Sin extensiones
    # instaladas, el paquete puede ni existir y '--check' sigue respondiendo.
    try:
        import htims
    except ImportError:
        print("\nextensiones (HTIMS): capa no disponible en este checkout")
        return

    root = project_root(config)
    manifiesto = os.path.join(root, htims.MANIFEST_FNAME)
    print(f"\nextensiones (HTIMS): {htims.MANIFEST_FNAME} ->", end=" ")
    if not os.path.isfile(manifiesto):
        print(f"no hay (se buscó en {root})")
    else:
        print(manifiesto)

    extensions, errors = htims.discover(dict(config))
    if extensions is not None and extensions.modules:
        if extensions.project:
            print(f"  proyecto: {extensions.project}")
        for module in extensions.modules:
            print(f"  [OK ] {module.path}  ({len(module.hooks)} hook(s))")
    elif not errors:
        print("  sin extensiones declaradas")
    for err in errors:
        print(f"  [ERROR] {err.code}: {err.message}  ({err.loc})")


def _print_report() -> int:
    print("suriaX - verificacion de dependencias\n")
    report = check_dependencies()
    all_ok = True
    for name, info in report.items():
        opcional = info.get("optional", False)
        if info["ok"]:
            mark = "OK "
        else:
            mark = "OPCIONAL" if opcional else "FALTA"
        print(f"  [{mark}] {name}: {info['detail']}")
        if not info["ok"]:
            if opcional:
                # una opcional que falta no es un fallo del entorno: se dice
                # para que sirve, y '--check' sigue terminando en 0
                print(f"          (opcional: {info['use']})")
            else:
                all_ok = False
            print(f"          -> {info['install']}")

    config = reload_config()
    problemas = errors_of(config)
    criticos = [e for e in problemas if e.severity == "critical"]
    print(f"\nconfiguracion: {CONFIG_FNAME} ->", end=" ")
    if not problemas:
        print("correcta")
    else:
        print("CON ERRORES" if criticos else "correcta, con avisos")
        for err in problemas:
            marca = "ERROR" if err.severity == "critical" else "AVISO"
            print(f"  [{marca}] {err.code}: {err.message}  ({err.loc})")
    # un aviso no tumba el reporte: 'pyyaml' es opcional para compilar.
    if criticos:
        all_ok = False

    print("\nplataforma:", "web" if IS_WEB else config["platform"])
    print("target:", config["target"])
    print("rutas .libsrx:", ", ".join(config["libraries"]["libsrx_paths"]))
    _print_extensions(config)
    cache_report = verify_cache(config)
    print(f"\ncache: {cache_report['dir']}  "
          f"({cache_report['fresh']} vigentes, {cache_report['pruned']} podadas)")
    return 0 if all_ok else 1


__all__ = [
    # dependencias / plataforma
    "IS_WIN32", "IS_LINUX", "IS_MACOS", "IS_WEB",
    "DependencyError", "check_dependencies", "ensure_dependencies",
    # configuración
    "CONFIG_FNAME", "ERRORS_KEY", "default_config", "generate_config",
    "reload_config", "errors_of", "project_root", "resolve_path",
    "ConfigError", "validate",
    # salidas
    "CompilerLog", "DebugReport",
    "dump_ast_json", "dump_hir", "dump_tokens_txt", "dumps_dir",
    "ensure_cache_dir", "verify_cache",
]


if __name__ == "__main__":
    raise SystemExit(_print_report())
