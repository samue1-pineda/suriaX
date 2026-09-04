"""Formato de compilación ``.suriaX_config.yaml``: esquema, generación y carga.

Módulo del paquete ``config/``. Es la ÚNICA fuente de verdad del esquema de
configuración; cualquier fase que necesite una ruta o un flag lo consulta
aquí, nunca hardcodeado.

**Resolución de rutas (fix de la búsqueda "extraña")**: toda ruta relativa
del yaml (``libraries.libsrx_paths``, ``output.*``, ``logging.dir``,
``cache.dir``) se resuelve **relativa a la raíz del proyecto** — el
directorio donde vive el ``.suriaX_config.yaml`` (o el CWD si no hay
archivo de config). Antes se resolvían contra el CWD del proceso, así que
compilar desde otro directorio cambiaba silenciosamente dónde se buscaban
las librerías. La configuración cargada lleva ``_root`` con esa raíz;
:func:`resolve_path` centraliza la regla.
"""

from __future__ import annotations

import os
from typing import List, Optional

from . import dependencies as deps
from .errors import CFG001, CFG002, CFG007, ConfigError
from .validate import validate

CONFIG_FNAME = ".suriaX_config.yaml"


#: clave donde viajan los diagnosticos de la carga. Guion bajo = valor
#: resuelto en memoria, no parte del yaml que el usuario escribe (misma
#: convencion que ``_root`` y ``_extensions``).
ERRORS_KEY = "_errors"


def errors_of(config: Optional[dict]) -> List[ConfigError]:
    """Diagnosticos que dejo la carga de ``config`` (lista vacia si ninguno)."""
    return list((config or {}).get(ERRORS_KEY) or [])


def default_config() -> dict:
    """Esquema del formato de compilación con la información que cada fase
    necesita: toolchain, target, salidas (volcados/logs/caché) y búsqueda de
    librerías nativas.
    """
    return {
        "version": 2,
        # target de ejecución. Todos parten del MISMO HIR (el contrato que
        # desacopla el frontend de sus consumidores, ver ARCHITECTURE.md):
        #   native  -> HIR -> MIR -> VM bytecode/JIT -> objeto/ejecutable
        #   wasm    -> íd., artefacto .wasm
        #   interp  -> HIR -> intérprete tree-walk en Python (runtime/interpreter/)
        # El target PRINCIPAL del proyecto es 'interp' (Pre-Alpha: única ruta
        # que ejecuta), y así viene en el .suriaX_config.yaml del repo. Pero
        # este DEFAULT en memoria — el fallback cuando NO hay yaml o no se pudo
        # cargar — se mantiene 'native' a propósito: es el contrato de
        # "Python pelado" (how_to_run.md secc. 3, tests e2e/stdlib-only), donde
        # el frontend compila y reporta SIN protobuf. Poner 'interp' aquí
        # forzaría protobuf en ese camino mínimo. Los flujos que SÍ ejecutan no
        # dependen de este fallback: el yaml del repo trae 'interp' y
        # 'python main.py archivo.srcx' fuerza --run.
        "target": "wasm" if deps.IS_WEB else "native",  # native | wasm | interp
        "platform": (
            "win32" if deps.IS_WIN32 else "linux" if deps.IS_LINUX else
            "macos" if deps.IS_MACOS else "unknown"
        ),
        "optimization": "O0",  # O0 | O1 | O2 | O3

        # --- toolchain: lo que hace falta para COMPILAR, no para usar el
        # compilador. Todo lo de aqui es del compilador (suriaX); las
        # herramientas que lo rodean (suriniX) no ponen nada en esta seccion.
        #
        # El target nativo es la VM de bytecode con JIT; LLVM no esta en la
        # ruta de generacion de codigo (ver ARCHITECTURE.md), asi que aqui no
        # hay nada suyo que configurar.
        "toolchain": {
            "linker": deps.detect_linker(),
            "sysroot": os.environ.get("SURIAX_SYSROOT", ""),

            # --- '#extern cpp' / '#extern c': un COMPILADOR, no un build
            # system. Traer codigo de C++ no puede exigirle al usuario un
            # CMake ni un Makefile: se detecta el compilador que ya tiene y
            # se invoca. Vacio = detectar; escrito = usar ese y no buscar.
            "cxx_compiler": deps.detect_cxx(),
            "c_compiler": deps.detect_cc(),
            # rutas de cabeceras para los bloques '#extern' (cada una entra
            # como '-I<ruta>'). Aqui va lo que un tercero instalo en un sitio
            # que el compilador no mira por defecto.
            "include_c_paths": [],
            # banderas que el USUARIO anade a la compilacion de sus bloques.
            # Es donde vive '-lGL', '-lX11' o '-pthread': dependen de la
            # maquina y de lo que el bloque use, no del lenguaje.
            "cxx_flags": [],
            "c_flags": [],
        },

        # --- target detallado: triple/arch/artefacto + opciones wASM ---
        "codegen": {
            "triple": deps.detect_target_triple(),
            "arch": deps.machine_arch(),
            "artifact": deps.default_artifact(),   # o | exe | wasm
            "wasm": {
                "enabled": deps.IS_WEB,
                "stack_size": 1048576,
                "export_all": False,
            },
        },

        # --- salidas del compilador (cada tipo en su carpeta) ---
        "output": {
            "dumps_dir": "./dumps",   # volcados: AST .json, tokens .txt
            "build_dir": "./build",   # artefactos del build (futuro suriniX)
        },
        "logging": {
            "dir": "./log",          # <fuente>.log (por archivo) + notes.jsonl / errors.jsonl
            "enabled": True,
        },
        "cache": {
            "dir": "./build/cache",  # entrada al runtime system / suriniX
            "enabled": True,
        },

        # --- intérprete tree-walk (target 'interp'): consume el HIR ---
        # Knobs modificables por el usuario. Solo tienen efecto con
        # 'target: interp' (o 'python V0/main.py archivo.srcx --run').
        # Diseño: runtime/interpreter/ARQUITECTURA.md.
        "interpreter": {
            "entry": "main",         # función de entrada a ejecutar
            "trace_memory": False,   # traza regiones/move en runtime (educativo)
            "max_steps": 0,          # 0 = sin límite; guarda contra bucles infinitos
        },

        # --- visualización: qué etapas volcar (objetivo educativo) ---
        "visualization": {
            "stages": [],        # p.ej. ["tokens", "ast", "hir", "mir", "bytecode"]
            "format": "text",    # text | json | dot
        },

        # --- librerías nativas: búsqueda de .libsrx y bindings C++ ---
        # Rutas RELATIVAS A LA RAÍZ DEL PROYECTO (donde vive este yaml).
        # Por defecto solo './lib'; el usuario añade las suyas aquí.
        "libraries": {
            "libsrx_paths": ["./lib"],
            "extern_cpp_include": [],   # headers C++ para '#extern cpp{}'
            "bindings": [],             # módulos pybind11 a enlazar
        },

        # --- extensiones del proyecto (HTIMS) -------------------------------
        # Las declara 'extends.srcx' (manifiesto en la raíz: logic_dir C++ /
        # calls_dir Python) o se escriben a mano aquí:
        #
        #   project: "MiJuego"
        #   extensions:
        #     - path: "plugins/physics.py"
        #
        # 'project' lo DECLARA la extensión ('PROJECT = "MiJuego"' en su .py,
        # no el nombre de los archivos); escribirlo a mano solo tiene efecto
        # en un proyecto que no declara ninguna. El descubrimiento corre ANTES
        # del léxico y vive en 'htims/' — este paquete solo define el esquema.
        "project": "",
        "extensions": [],

        "paths": {
            "input": "",
            "output": "out",
        },
        "flags": {
            "is_web": deps.IS_WEB,
        },
    }


def generate_config(path: Optional[str] = None, *, overwrite: bool = False) -> str:
    """Genera el ``.suriaX_config.yaml`` por defecto y devuelve su ruta.

    No sobreescribe un archivo existente salvo ``overwrite=True``.
    """
    import yaml  # local: pyyaml es una dependencia verificada aparte

    target = path or os.path.join(os.getcwd(), CONFIG_FNAME)
    if os.path.exists(target) and not overwrite:
        return target

    with open(target, "w", encoding="utf-8") as fh:
        yaml.safe_dump(default_config(), fh, sort_keys=False, allow_unicode=True)
    return target


def _find_config_file(start_dir: Optional[str] = None) -> Optional[str]:
    """Busca el ``.suriaX_config.yaml`` subiendo desde ``start_dir`` (o CWD)
    hasta la raíz del sistema — así compilar desde un subdirectorio del
    proyecto encuentra la MISMA config que compilar desde la raíz."""
    current = os.path.abspath(start_dir or os.getcwd())
    while True:
        candidate = os.path.join(current, CONFIG_FNAME)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def reload_config(path: Optional[str] = None, *, start_dir: Optional[str] = None) -> dict:
    """Carga la configuración desde ``.suriaX_config.yaml``.

    - ``path`` explícito gana; si no, se busca subiendo desde ``start_dir``
      (típicamente el directorio del ``.srcx``) o el CWD.
    - Sin archivo -> defaults (sin escribir nada en disco).
    - La config devuelta lleva ``_root``: la raíz contra la que se resuelven
      las rutas relativas (dir del yaml, o ``start_dir``/CWD si no hay yaml).
    """
    target = path or _find_config_file(start_dir)
    if target is None or not os.path.isfile(target):
        config = default_config()
        config["_root"] = os.path.abspath(start_dir or os.getcwd())
        config[ERRORS_KEY] = []
        return config

    root = os.path.dirname(os.path.abspath(target))
    config = default_config()
    errores: List[ConfigError] = []
    # Encontrar el archivo ya define la raiz del proyecto, pase lo que pase al
    # leerlo: perderla mandaria la resolucion de rutas al CWD del proceso.
    # Lo que ya NO se hace es seguir en silencio — una config que no dice lo
    # que su autor cree es peor que no tenerla, y el sintoma aparecia lejos
    # ("no se encontro la libreria X") sin pista del origen.
    data = None
    try:
        import yaml
    except ImportError:
        # ADVERTENCIA, no error: el frontend completo corre con la libreria
        # estandar (contrato de how_to_run.md), asi que no tener el lector de
        # yaml no puede impedir compilar. Pero callarlo es peor: el usuario
        # cree que su config se aplica y esta usando los valores por defecto.
        errores.append(ConfigError(
            CFG007,
            "hay un '.suriaX_config.yaml' pero falta 'pyyaml' para leerlo: la "
            "configuracion NO se esta aplicando y todo usa los valores por "
            "defecto -> pip install pyyaml",
            file=target, severity="warning",
        ))
    else:
        try:
            with open(target, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
        except OSError as exc:
            errores.append(ConfigError(
                CFG001, f"no se pudo leer la configuracion: {exc}", file=target))
        except UnicodeDecodeError as exc:
            errores.append(ConfigError(
                CFG001, f"la configuracion no es UTF-8 valido: {exc}", file=target))
        except yaml.YAMLError as exc:
            marca = getattr(exc, "problem_mark", None)
            errores.append(ConfigError(
                CFG002,
                f"YAML malformado: {getattr(exc, 'problem', None) or exc}",
                file=target,
                line=(marca.line + 1) if marca else 1,
                column=(marca.column + 1) if marca else 1,
            ))

    if data is not None:
        errores.extend(validate(data, default_config(), archivo=target))
        # mezcla superficial sobre los defaults para tolerar archivos parciales.
        # Solo se aplica lo que VALIDA: aplicar un valor que ya se reporto como
        # erroneo haria que el compilador trabajara con datos que acaba de
        # rechazar.
        if not errores and isinstance(data, dict):
            config.update(data)
    config["_root"] = root
    config[ERRORS_KEY] = errores
    return config


def project_root(config: Optional[dict]) -> str:
    """Raíz del proyecto según la config (fallback: CWD)."""
    if config:
        root = config.get("_root")
        if root:
            return root
    return os.getcwd()


def resolve_path(config: Optional[dict], path: str) -> str:
    """Resuelve ``path`` contra la raíz del proyecto si es relativo.

    Regla ÚNICA de resolución de rutas de la configuración: los absolutos
    pasan intactos; ``~`` se expande; lo relativo se ancla a
    :func:`project_root` — nunca al CWD del proceso.
    """
    path = os.path.expanduser(path)
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(project_root(config), path))


__all__ = [
    "CONFIG_FNAME", "ERRORS_KEY", "default_config", "generate_config",
    "reload_config", "errors_of", "project_root", "resolve_path",
]
