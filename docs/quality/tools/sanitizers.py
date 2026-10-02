"""Sanitizadores: construye la VM (``suriax-hir``) instrumentada y corre con
ella las categorías de la suite que la ejercitan (``backend`` y
``bootstrap``, que compilan y ejecutan programas reales en la VM).

- **ASan** (AddressSanitizer): desbordes, uso tras liberar, dobles
  liberaciones. MSVC lo trae (``/fsanitize=address``); GCC y Clang también.
- **UBSan** (UndefinedBehaviorSanitizer): desborde con signo, corrimientos
  fuera de rango, conversiones inválidas, alineación. MSVC no lo tiene; se usa
  Clang. Si Clang no trae el runtime de UBSan para la arquitectura (el caso de
  un LLVM de Windows sin compiler-rt x64), se usa el modo TRAMPA
  (``SURIAX_SANITIZE_TRAP``): detiene el programa sin decir qué regla rompió.

Cada build va a su propia carpeta (``build-asan``, ``build-ubsan``) y no toca
el build normal. Un hallazgo del sanitizador hace fallar la prueba que lo
disparó: la corrida se cuenta con el mismo runner de la suite.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from typing import Dict, List, Optional

from common import ROOT, find_tool, msvc_environment, percent, python_exe, rel, run

#: las categorías de la suite que corren programas en la VM
CATEGORIES = ["backend", "bootstrap"]


def _binary(build_dir: str) -> Optional[str]:
    for name in ("suriax-hir", "suriax-hir.exe"):
        path = os.path.join(build_dir, "bin", name)
        if os.path.isfile(path):
            return path
    return None


def _clang_has_ubsan_runtime(clang: str, env: Optional[Dict[str, str]]) -> bool:
    """Si ``clang`` puede ENLAZAR un programa con ``-fsanitize=undefined``
    (sin trampa): se prueba compilando uno mínimo."""
    with tempfile.TemporaryDirectory(prefix="suriax-ubsan-probe-") as tmp:
        src = os.path.join(tmp, "p.cpp")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write("int main(int c, char**) { return c << 1; }\n")
        out = run(
            [
                clang,
                *_clang_target(),
                "-fsanitize=undefined",
                src,
                "-o",
                os.path.join(tmp, "p.exe" if os.name == "nt" else "p"),
            ],
            cwd=tmp,
            env=env,
        )
        return out.returncode == 0


def _trap_fires(clang: str, env: Optional[Dict[str, str]]) -> bool:
    """El control de la trampa: un desborde con signo compilado con las
    MISMAS banderas tiene que detener el programa. Si no lo hace, una suite
    "limpia" bajo UBSan no probaría nada."""
    with tempfile.TemporaryDirectory(prefix="suriax-ubsan-trap-") as tmp:
        src = os.path.join(tmp, "ub.cpp")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(
                "#include <climits>\n"
                "int main(int argc, char**) { int x = INT_MAX; x += argc; return x == 0; }\n"
            )
        exe = os.path.join(tmp, "ub.exe" if os.name == "nt" else "ub")
        linker = ["-fuse-ld=link"] if os.name == "nt" else []
        built = run(
            [
                clang,
                *_clang_target(),
                *linker,
                "-O0",
                "-fsanitize=undefined",
                "-fsanitize-trap=undefined",
                src,
                "-o",
                exe,
            ],
            cwd=tmp,
            env=env,
        )
        if built.returncode != 0:
            return False
        # sin trampa sale con 0 (x == INT_MIN != 0); con ella, lo mata el sistema
        return run([exe], cwd=tmp).returncode not in (0, 1)


def _clang_target() -> List[str]:
    """En Windows, clang de LLVM puede venir apuntando a 32 bits; el build de
    la VM es de 64, contra las bibliotecas de MSVC x64."""
    return ["--target=x86_64-pc-windows-msvc"] if os.name == "nt" else []


def configure_and_build(kind: str) -> dict:
    """Configura y construye ``build-<kind>`` (``asan`` o ``ubsan``)."""
    build_dir = os.path.join(ROOT, f"build-{kind}")
    env = msvc_environment() if os.name == "nt" else dict(os.environ)
    if os.name == "nt" and env is None:
        return {"built": False, "reason": "no se encontró Visual Studio (vcvars64)"}
    cmake = find_tool("cmake", "CMAKE")
    ninja = find_tool("ninja", "NINJA") or (
        shutil.which("ninja", path=env.get("PATH")) if env else None
    )
    if cmake is None:
        return {"built": False, "reason": "cmake no está instalado"}
    args = [
        cmake,
        "-S",
        ROOT,
        "-B",
        build_dir,
        "-DSURIAX_BUILD_NATIVE=OFF",
        "-DCMAKE_BUILD_TYPE=Debug",
    ]
    if ninja:
        args += ["-G", "Ninja"]
    notes: List[str] = []
    if kind == "asan":
        args.append("-DSURIAX_SANITIZE=address")
        if os.name == "nt":
            args.append("-DCMAKE_CXX_COMPILER=cl")
    else:
        clang = find_tool("clang++", "CLANGXX")
        if clang is None:
            return {"built": False, "reason": "UBSan necesita clang++ (MSVC no lo tiene)"}
        args += [f"-DCMAKE_CXX_COMPILER={clang}", "-DSURIAX_SANITIZE=undefined"]
        if _clang_target():
            args.append(f"-DCMAKE_CXX_FLAGS={' '.join(_clang_target())}")
        if os.name == "nt" and not (find_tool("lld-link") or find_tool("ld.lld")):
            # CMake pide '-fuse-ld=lld' a clang en Windows; sin lld, el
            # enlazador de MSVC (link.exe, del entorno de vcvars)
            args.append("-DCMAKE_LINKER_TYPE=MSVC")
        if not _clang_has_ubsan_runtime(clang, env):
            args.append("-DSURIAX_SANITIZE_TRAP=ON")
            notes.append(
                "clang no trae el runtime de UBSan para esta arquitectura: modo "
                "trampa (detiene el programa; no dice qué regla se rompió)"
            )
            if _trap_fires(clang, env):
                notes.append("trampa verificada: un desborde con signo detiene el programa")
            else:
                return {
                    "built": False,
                    "reason": "la trampa de UBSan no se dispara con un desborde con signo: "
                    "una suite limpia no probaría nada",
                }
        else:
            args.append("-DSURIAX_SANITIZE_TRAP=OFF")
    configured = run(args, env=env)
    if configured.returncode != 0:
        return {
            "built": False,
            "reason": "falló la configuración de CMake",
            "log": (configured.stdout + configured.stderr)[-3000:],
        }
    built = run([cmake, "--build", build_dir, "--target", "suriax-hir"], env=env, timeout=7200)
    binary = _binary(build_dir)
    if built.returncode != 0 or binary is None:
        return {
            "built": False,
            "reason": "falló la compilación",
            "log": (built.stdout + built.stderr)[-3000:],
        }
    return {"built": True, "binary": rel(binary), "notes": notes, "env": env}


def run_suite(binary: str, env: Optional[Dict[str, str]], kind: str) -> dict:
    """Las categorías que usan la VM, con el binario instrumentado."""
    summary = os.path.join(ROOT, "docs", "quality", "reports", f"suite-{kind}.json")
    os.makedirs(os.path.dirname(summary), exist_ok=True)
    env = dict(env or os.environ)
    env["SURIAX_HIR_BIN"] = os.path.join(ROOT, binary)
    env["PYTHONUTF8"] = "1"
    if kind == "asan":
        # un hallazgo detiene el proceso (y la prueba falla); los retornos de
        # pila también se vigilan
        env["ASAN_OPTIONS"] = "halt_on_error=1:detect_stack_use_after_return=1"
    else:
        env["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
    out = run(
        [python_exe(), os.path.join("test", "main.py"), *CATEGORIES, "--json", summary],
        env=env,
        timeout=14400,
    )
    with open(summary, encoding="utf-8") as fh:
        data = json.load(fh)
    reports = [
        line
        for line in (out.stdout + out.stderr).splitlines()
        if "Sanitizer" in line or "runtime error:" in line
    ]
    return {
        "categories": CATEGORIES,
        "passed": data["passed"],
        "failed": data["failed"],
        "skipped": data["skipped"],
        "total": data["total"],
        "clean_pct": percent(data["passed"], data["passed"] + data["failed"]),
        "failures": [f"{f.get('module')}::{f.get('test')}" for f in data.get("failures", [])],
        "sanitizer_reports": reports[:50],
    }


def measure(kinds: Optional[List[str]] = None) -> dict:
    """Construye y corre cada sanitizador pedido (por defecto, los dos)."""
    result = {}
    for kind in kinds or ["asan", "ubsan"]:
        print(f"  sanitizers: construyendo build-{kind}...", flush=True)
        build = configure_and_build(kind)
        if not build["built"]:
            result[kind] = {"measured": False, **build}
            continue
        env = build.pop("env")
        print(
            f"  sanitizers: corriendo {', '.join(CATEGORIES)} con {build['binary']}...", flush=True
        )
        result[kind] = {"measured": True, **build, **run_suite(build["binary"], env, kind)}
    return result
