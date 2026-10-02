"""Lo que comparten las automatizaciones de calidad: rutas, alcance, cómo
encontrar una herramienta y cómo correrla sin depender del sistema.

Nada de aquí corre con ``test/main.py``: la calidad se mide a pedido, en los
lotes grandes (ver ``docs/quality/README.md``).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Sequence

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
QUALITY = os.path.join(ROOT, "docs", "quality")
#: salidas crudas de cada herramienta (se regeneran; no se versionan)
REPORTS = os.path.join(QUALITY, "reports")
#: documentos de cumplimiento generados a partir de REPORTS
COMPLIANCE = os.path.join(QUALITY, "cumplimiento")

#: el código Python del COMPILADOR que se mide (el target web queda fuera:
#: es TypeScript y tiene sus propias normas). 'test' se mide aparte.
PY_SCOPE = ["V0", "runtime", "htims", "config", "suri", "dev", "main.py", "version.py"]
PY_TESTS = ["test"]

#: el C++ que se mide: la VM y el lector del HIR, y el módulo nativo de memoria
CPP_DIRS = ["backend/src", "backend/tools", "backend/include", "runtime/logic_mem"]
CPP_EXTENSIONS = (".cpp", ".cc", ".cxx", ".hpp", ".h")

_SKIP_DIRS = {"__pycache__", "node_modules", ".git", "gen"}


def rel(path: str) -> str:
    """Ruta relativa a la raíz, con ``/`` (estable entre sistemas)."""
    try:
        return os.path.relpath(os.path.abspath(path), ROOT).replace(os.sep, "/")
    except ValueError:  # otra unidad en Windows
        return path.replace(os.sep, "/")


def iter_files(entries: Sequence[str], extensions: Sequence[str]) -> List[str]:
    """Los archivos de ``entries`` (carpetas o archivos, relativos a la raíz)
    con esas extensiones, sin cachés, builds ni temporales de la suite."""
    found: List[str] = []
    for entry in entries:
        base = os.path.join(ROOT, entry)
        if os.path.isfile(base):
            if base.endswith(tuple(extensions)):
                found.append(base)
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(
                d
                for d in dirnames
                if d not in _SKIP_DIRS and not d.startswith(("build", "suriax-"))
            )
            found.extend(
                os.path.join(dirpath, f)
                for f in sorted(filenames)
                if f.endswith(tuple(extensions))
            )
    return found


def count_lines(files: Sequence[str]) -> int:
    """Líneas de texto de ``files`` (para las medidas por cada 1000 líneas)."""
    total = 0
    for path in files:
        with open(path, encoding="utf-8", errors="replace") as fh:
            total += sum(1 for _ in fh)
    return total


def find_tool(name: str, env_var: Optional[str] = None) -> Optional[str]:
    """La herramienta ``name``: la de la variable ``env_var`` si existe, si no
    la del PATH. ``None`` si no está: quien llama lo reporta como NO MEDIDO,
    nunca como cumplido."""
    if env_var and os.environ.get(env_var):
        candidate = os.environ[env_var]
        return candidate if os.path.isfile(candidate) or shutil.which(candidate) else None
    return shutil.which(name)


def python_module_available(module: str) -> bool:
    """Si ``python -m module`` existe en este intérprete."""
    import importlib.util

    return importlib.util.find_spec(module) is not None


def run(
    cmd: Sequence[str],
    *,
    cwd: str = ROOT,
    env: Optional[Dict[str, str]] = None,
    timeout: int = 3600,
) -> subprocess.CompletedProcess:
    """Corre ``cmd`` y devuelve su salida como texto UTF-8 (lo que no lo sea
    se reemplaza: un carácter roto no puede tumbar la medición)."""
    return subprocess.run(
        list(cmd),
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def tool_version(cmd: Sequence[str]) -> str:
    """La primera línea de ``cmd --version`` (para el informe), o ``""``."""
    try:
        out = run(cmd, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    lines = (out.stdout or out.stderr).strip().splitlines()
    return lines[0].strip() if lines else ""


def save_report(name: str, data: dict) -> str:
    """Guarda ``reports/<name>.json`` y devuelve la ruta."""
    os.makedirs(REPORTS, exist_ok=True)
    path = os.path.join(REPORTS, f"{name}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return path


def load_report(name: str) -> Optional[dict]:
    """El último ``reports/<name>.json``, o ``None`` si nunca se midió."""
    path = os.path.join(REPORTS, f"{name}.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def percent(part: float, total: float) -> Optional[float]:
    """``part / total`` en porcentaje con un decimal; ``None`` sin total."""
    if not total:
        return None
    return round(100.0 * part / total, 1)


def msvc_environment() -> Optional[Dict[str, str]]:
    """El entorno de ``vcvars64.bat`` (Windows) para compilar con MSVC o con
    clang contra las cabeceras de MSVC. ``None`` fuera de Windows o si no
    hay Visual Studio. Se usa ``vswhere`` (viene con el instalador)."""
    if os.name != "nt":
        return None
    if shutil.which("cl"):
        return dict(os.environ)  # ya estamos en una consola de VS
    vswhere = os.path.join(
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        "Microsoft Visual Studio",
        "Installer",
        "vswhere.exe",
    )
    if not os.path.isfile(vswhere):
        return None
    found = run([vswhere, "-latest", "-products", "*", "-property", "installationPath"])
    install = found.stdout.strip().splitlines()
    if not install:
        return None
    vcvars = os.path.join(install[0], "VC", "Auxiliary", "Build", "vcvars64.bat")
    if not os.path.isfile(vcvars):
        return None
    dump = subprocess.run(
        f'"{vcvars}" >nul && set',
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    env = {}
    for line in dump.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            env[key] = value
    return env or None


def python_exe() -> str:
    """El intérprete que corre esto (no ``python3`` a mano)."""
    return sys.executable
