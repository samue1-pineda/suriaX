#!/usr/bin/env python3
"""Diferencial de suriaX (dev/diff): esquema 1 frente a 2 del HIR, y
compilador V0 frente a V1, en tres targets (intérprete, VM y web).

Para cada programa de ``dev/diff/programs/`` se emiten TRES ``.phir``, cada uno
con sus unidades de librería en su carpeta:

- ``s1``: la V0 con ``--hir-schema 1`` (el esquema inicial: tipos inline);
- ``s2``: la V0 con ``--hir-schema 2`` (el de hoy: pool de tipos);
- ``v1``: el compilador V1 (escrito en suriaX, en la VM), que emite el 2.

Se mide la EMISIÓN de cada uno y el tamaño; y con cada ``.phir`` y en cada
target, la LECTURA (cargar y ligar sin ejecutar) y la EJECUCIÓN, con la
salida y el código comparados con la REFERENCIA (el intérprete con ``s2``).
Cada celda queda OK, NOT SUPPORTED (un rechazo explícito con código) o ERROR
(una divergencia de verdad).

La comparación PRINCIPAL es ``s1`` frente a ``s2`` (el esquema); la de
compiladores (``s2`` frente a ``v1``) es un apartado aparte.

Cada medida se repite ``--reps`` veces (30 por defecto); la primera se
descarta; se informa la MEDIANA de las restantes, con mínimo, máximo y rango
intercuartílico. Si la corrida de calentamiento dice que una celda pasaría de
``--cell-budget`` segundos, esa celda (y solo esa) hace menos corridas, y se
dice en ``RESULTS.md``.

Escribe ``dev/diff/RESULTS.md`` y ``dev/diff/results.json``; los artefactos van
a ``dev/diff/work/`` (ignorado por git).

Uso (desde la raíz del repositorio):
    python dev/diff/run_diff.py --reps 3          # prueba rápida
    python dev/diff/run_diff.py                   # la corrida completa (30)
    python dev/diff/run_diff.py --only 01 08      # solo esos programas
    python dev/diff/run_diff.py --render-only     # rehace RESULTS.md sin medir
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import time
from typing import Callable, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PROGRAMS_DIR = os.path.join(HERE, "programs")
WORK = os.path.join(HERE, "work")
V0_MAIN = os.path.join(REPO, "V0", "main.py")
STDLIB = os.path.join(REPO, "lib")
READ_INTERP = os.path.join(HERE, "read_interp.py")
READ_WEB = os.path.join(HERE, "read_web.ts")
INTERP_MAIN = os.path.join(REPO, "runtime", "interpreter", "main.py")
WEB_MAIN = os.path.join(REPO, "web", "main.ts")
#: los paquetes de la V1 que van a la 'lib/' de su proyecto (como
#: test/bootstrap/test_bootstrap_v1.py)
V1_PACKAGES = ("frontend", "semantica", "hir")

#: los tres .phir de cada programa (ver el docstring)
HIRS = ("s1", "s2", "v1")
HIR_SHORT = {"s1": "esquema 1", "s2": "esquema 2", "v1": "compilador V1"}
HIR_NAMES = {"s1": "esquema 1 (compilador V0, `--hir-schema 1`)",
             "s2": "esquema 2 (compilador V0, `--hir-schema 2`)",
             "v1": "compilador V1 (esquema 2)"}
#: la referencia de las comparaciones: el intérprete con este .phir
REF_HIR = "s2"
TARGETS = ("interp", "vm", "web")
TARGET_NAMES = {"interp": "intérprete (Python)", "vm": "VM (C++)", "web": "web (WebAssembly)"}
#: la marca que el CLI del web escribe a stderr al terminar 'main' (la VM la
#: calla con --quiet; el intérprete no la escribe). No es salida del programa.
BANNER = re.compile(rb"^\[(wasm|js)\] main\(\) -> -?\d+\r?\n", re.M)
CONFIG_YAML = "version: 1\ntarget: native\n"


# --------------------------------------------------------------------------
# herramientas
# --------------------------------------------------------------------------

def find_vm(explicit: Optional[str]) -> str:
    candidates = [explicit, os.environ.get("SURIAX_HIR_BIN"),
                  os.path.join(REPO, "build", "bin", "suriax-hir.exe"),
                  os.path.join(REPO, "build", "bin", "suriax-hir")]
    for c in candidates:
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    sys.exit("no se encontró la VM (build/bin/suriax-hir): constrúyela (README.md §2) "
             "o pásala con --vm / SURIAX_HIR_BIN")


def find_node(explicit: Optional[str]) -> str:
    candidates = [explicit, os.environ.get("SURIAX_NODE"), shutil.which("node"),
                  r"C:\Program Files\nodejs\node.exe"]
    for c in candidates:
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    sys.exit("no se encontró node (>= 23): ponlo en el PATH o pásalo con --node / SURIAX_NODE")


def child_env() -> dict:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env.pop("PYTHONIOENCODING", None)
    return env


class Run:
    __slots__ = ("rc", "out", "err", "ms")

    def __init__(self, rc: int, out: bytes, err: bytes, ms: float) -> None:
        self.rc, self.out, self.err, self.ms = rc, out, err, ms

    def key(self) -> tuple:
        return (self.rc, hashlib.sha256(self.out).hexdigest(),
                hashlib.sha256(self.err).hexdigest())


def run_once(cmd: list, cwd: str, timeout: float) -> Run:
    """Una corrida: el tiempo es de pared, de 'Popen' a que el proceso
    termina (incluye arrancar el proceso: Python, node o la VM)."""
    t0 = time.perf_counter_ns()
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, env=child_env(),
                           timeout=timeout)
        rc, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as exc:
        rc, out, err = -999, exc.stdout or b"", (exc.stderr or b"") + \
            f"\n[arnés] TIEMPO AGOTADO tras {timeout:.0f} s\n".encode()
    t1 = time.perf_counter_ns()
    return Run(rc, out, err, (t1 - t0) / 1e6)


def stats(times: list) -> dict:
    if not times:
        return {}
    s = sorted(times)
    q = statistics.quantiles(s, n=4, method="inclusive") if len(s) >= 2 else [s[0]] * 3
    return {"n": len(s), "median_ms": statistics.median(s), "min_ms": s[0],
            "max_ms": s[-1], "q1_ms": q[0], "q3_ms": q[2]}


class Measurer:
    def __init__(self, reps: int, budget: float, min_runs: int, timeout: float,
                 log: Callable[[str], None]) -> None:
        self.reps, self.budget, self.min_runs = reps, budget, min_runs
        self.timeout, self.log = timeout, log

    def measure(self, label: str, cmd: list, cwd: str,
                prepare: Optional[Callable[[], None]] = None) -> dict:
        """``reps`` corridas (o menos, ver --cell-budget); la 1.ª se descarta."""
        if prepare:
            prepare()
        first = run_once(cmd, cwd, self.timeout)
        runs = self.reps
        reduced = None
        if self.reps > 1 and first.ms / 1000 * self.reps > self.budget:
            runs = max(self.min_runs, int(self.budget // max(first.ms / 1000, 1e-9)))
            runs = min(runs, self.reps)
            if runs < self.reps:
                reduced = (f"la corrida de calentamiento tardó {first.ms / 1000:.1f} s; "
                           f"{self.reps} corridas pasarían de {self.budget:.0f} s, "
                           f"así que esta celda hizo {runs} (1 descartada + {runs - 1})")
        all_runs = [first]
        for _ in range(runs - 1):
            if prepare:
                prepare()
            all_runs.append(run_once(cmd, cwd, self.timeout))
        timed = [r.ms for r in all_runs[1:]] if len(all_runs) > 1 else [first.ms]
        keys = {r.key() for r in all_runs}
        result = {
            "cmd": [str(c) for c in cmd], "cwd": cwd,
            "runs": len(all_runs), "warmup_ms": first.ms, "times_ms": timed,
            "stats": stats(timed), "reduced": reduced,
            "deterministic": len(keys) == 1,
            "rc": first.rc, "stdout": first.out, "stderr": first.err,
        }
        st = result["stats"]
        self.log(f"    {label:<34} rc={first.rc:<4} mediana {st['median_ms']:9.1f} ms "
                 f"[{st['min_ms']:.1f}–{st['max_ms']:.1f}] n={st['n']}"
                 + ("  (REDUCIDA)" if reduced else "")
                 + ("" if result["deterministic"] else "  (NO DETERMINISTA)"))
        return result


# --------------------------------------------------------------------------
# sin rutas de la máquina
# --------------------------------------------------------------------------

#: (ruta, cómo se escribe en lo publicado). Lo rellena register_paths() con
#: las herramientas encontradas; el repositorio y la carpeta personal, siempre.
_PATH_LABELS: list = []


def repo_relative(path: str) -> str:
    """Una ruta dentro del repositorio, relativa a él y con '/'."""
    try:
        rel = os.path.relpath(path, REPO)
    except ValueError:              # otra unidad en Windows
        return os.path.basename(path)
    return os.path.basename(path) if rel.startswith("..") else rel.replace(os.sep, "/")


def register_paths(vm: str, node: str) -> None:
    _PATH_LABELS.clear()
    _PATH_LABELS.extend([
        (sys.executable, "python"),
        (node, "node"),
        (vm, repo_relative(vm)),
        (os.path.join(REPO, "lib"), "<repo>/lib"),
        (REPO, "<repo>"),
        (os.path.expanduser("~"), "<home>"),
    ])


def _path_regex(path: str):
    """La ruta con cualquier separador ('\\' o '/'), con o sin 'file:///', sin
    distinguir mayúsculas (Windows)."""
    parts = [re.escape(x) for x in re.split(r"[\\/]+", os.path.abspath(path)) if x]
    return re.compile(r"(?:file:///)?" + r"[\\/]+".join(parts), re.I)


_UNDER_LABEL = re.compile(r"<(repo|home)>([\\/][^\s`'\"|)]*)")


def sanitize(text: str) -> str:
    """Quita de un texto publicado las rutas de ESTA máquina: Python, node, la
    VM, el repositorio ('<repo>') y la carpeta personal ('<home>'). Las más
    largas primero; lo que queda debajo de '<repo>' se escribe con '/'."""
    labels = _PATH_LABELS or [(REPO, "<repo>"), (os.path.expanduser("~"), "<home>")]
    for path, label in sorted(labels, key=lambda pl: -len(pl[0])):
        if path:
            text = _path_regex(path).sub(lambda _m, lb=label: lb, text)
    return _UNDER_LABEL.sub(lambda m: f"<{m.group(1)}>" + m.group(2).replace("\\", "/"), text)


# --------------------------------------------------------------------------
# entorno
# --------------------------------------------------------------------------

def _cmd_text(cmd: list, cwd: str = REPO) -> str:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=60)
        return p.stdout.decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def cpu_name() -> str:
    if sys.platform == "win32":
        text = _cmd_text(["powershell", "-NoProfile", "-Command",
                          "(Get-CimInstance Win32_Processor).Name"])
        return text or os.environ.get("PROCESSOR_IDENTIFIER", platform.processor())
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def cpu_load() -> str:
    """Carga de la CPU en este instante (Windows: % de uso; Linux: loadavg)."""
    if sys.platform == "win32":
        text = _cmd_text(["powershell", "-NoProfile", "-Command",
                          "(Get-CimInstance Win32_Processor | Measure-Object "
                          "-Property LoadPercentage -Average).Average"])
        return f"{text} % de uso de CPU (Win32_Processor.LoadPercentage)" if text else "?"
    if hasattr(os, "getloadavg"):
        a, b, c = os.getloadavg()
        return f"loadavg {a:.2f} {b:.2f} {c:.2f}"
    return "?"


def cxx_compiler() -> str:
    cache = os.path.join(REPO, "build", "CMakeCache.txt")
    info = {}
    try:
        with open(cache, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                for key in ("CMAKE_CXX_COMPILER:", "CMAKE_BUILD_TYPE:", "CMAKE_GENERATOR:"):
                    if line.startswith(key):
                        info[key[:-1]] = line.split("=", 1)[1].strip()
    except OSError:
        return "? (no hay build/CMakeCache.txt)"
    version = "?"
    files = os.path.join(REPO, "build", "CMakeFiles")
    for root, _dirs, names in os.walk(files):
        if "CMakeCXXCompiler.cmake" in names:
            with open(os.path.join(root, "CMakeCXXCompiler.cmake"), encoding="utf-8") as fh:
                text = fh.read()
            ident = re.search(r'CMAKE_CXX_COMPILER_ID "([^"]*)"', text)
            ver = re.search(r'CMAKE_CXX_COMPILER_VERSION "([^"]*)"', text)
            version = f"{ident.group(1) if ident else '?'} {ver.group(1) if ver else '?'}"
            break
    # solo el nombre y la versión: la ruta de cl.exe es de esta máquina
    return (f"{version} (build {info.get('CMAKE_BUILD_TYPE', '?')}, "
            f"{info.get('CMAKE_GENERATOR', '?')})")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def suriax_version() -> str:
    """La versión de suriaX, de su fuente única: 'version.py' en la raíz."""
    try:
        with open(os.path.join(REPO, "version.py"), encoding="utf-8") as fh:
            m = re.search(r'^VERSION\s*=\s*"([^"]+)"', fh.read(), re.M)
        return m.group(1) if m else "?"
    except OSError:
        return "?"


def _pyyaml_version() -> str:
    """La V0 lee '.suriaX_config.yaml' con pyyaml; sin él usa los valores por
    defecto (y avisa). Se anota porque cambia lo que imprime la emisión."""
    try:
        import yaml  # type: ignore
        return yaml.__version__
    except ImportError:
        return "no instalado"


def environment(vm: str, node: str) -> dict:
    head = _cmd_text(["git", "rev-parse", "HEAD"])
    dirty = _cmd_text(["git", "status", "--porcelain", "--untracked-files=no"])
    diff = subprocess.run(["git", "diff", "HEAD"], cwd=REPO, capture_output=True).stdout
    return {
        "date": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "os": platform.platform(),
        "cpu": cpu_name(),
        "logical_cpus": os.cpu_count(),
        "python": "Python " + sys.version.split()[0],
        "node": "node " + _cmd_text([node, "--version"]),
        "pyyaml": _pyyaml_version(),
        "cxx": cxx_compiler(),
        "vm_binary": f"{repo_relative(vm)} (sha256 {sha256_file(vm)[:16]}…)",
        "suriax_version": suriax_version(),
        "commit": head,
        "dirty_files": len(dirty.splitlines()) if dirty else 0,
        "diff_sha256": hashlib.sha256(diff).hexdigest()[:16] if dirty else "",
        "clock": str(time.get_clock_info("perf_counter")),
        "load_before": cpu_load(),
    }


# --------------------------------------------------------------------------
# la V1
# --------------------------------------------------------------------------

def build_v1(log) -> str:
    """Arma el proyecto de la V1 (como test_bootstrap_v1._v1) y la compila
    con la V0. Devuelve la ruta de su .phir."""
    v1dir = os.path.join(WORK, "v1")
    shutil.rmtree(v1dir, ignore_errors=True)
    shutil.copytree(STDLIB, os.path.join(v1dir, "lib"))
    for pkg in V1_PACKAGES:
        shutil.copytree(os.path.join(REPO, "src", pkg), os.path.join(v1dir, "lib", pkg))
    shutil.copy(os.path.join(REPO, "src", "main.srcx"), v1dir)
    with open(os.path.join(v1dir, ".suriaX_config.yaml"), "w", encoding="utf-8") as fh:
        fh.write(CONFIG_YAML)
    r = run_once([sys.executable, V0_MAIN, "main.srcx", "--emit-hir"], v1dir, 1800)
    phir = os.path.join(v1dir, "dumps", "main.srcx.phir")
    if r.rc != 0 or not os.path.isfile(phir):
        sys.exit("la V0 no compila la V1:\n" + r.out.decode("utf-8", "replace")
                 + r.err.decode("utf-8", "replace"))
    log(f"V1 compilada por la V0 en {r.ms / 1000:.1f} s -> {os.path.relpath(phir, REPO)}")
    return phir


# --------------------------------------------------------------------------
# un programa
# --------------------------------------------------------------------------

def unit_files(folder: str) -> dict:
    if not os.path.isdir(folder):
        return {}
    return {n: os.path.join(folder, n) for n in sorted(os.listdir(folder)) if n.endswith(".phir")}


def compare_units(a: dict, b: dict) -> dict:
    names = sorted(set(a) | set(b))
    same, differ = [], []
    for n in names:
        if n in a and n in b:
            with open(a[n], "rb") as fa, open(b[n], "rb") as fb:
                (same if fa.read() == fb.read() else differ).append(n)
        else:
            differ.append(n)
    return {"same": same, "differ": differ, "all_equal": bool(names) and not differ}


def sizes(files: dict, main_name: str) -> dict:
    total = sum(os.path.getsize(p) for p in files.values())
    main = os.path.getsize(files[main_name]) if main_name in files else None
    return {"main_bytes": main, "all_units_bytes": total, "units": len(files)}


def lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def no_banner(data: bytes) -> bytes:
    return BANNER.sub(b"", lf(data))


def common_prefix_lines(a: bytes, b: bytes) -> int:
    n = 0
    for x, y in zip(a.split(b"\n"), b.split(b"\n")):
        if x != y:
            break
        n += 1
    return n


def target_cmds(t: str, phir: str, vm: str, node: str) -> tuple:
    """(lectura, ejecución) de un target sobre un .phir."""
    if t == "interp":
        return ([sys.executable, READ_INTERP, phir],
                [sys.executable, INTERP_MAIN, phir, "--exec"])
    if t == "vm":
        return [vm, phir, "--link"], [vm, phir, "--run", "--quiet"]
    return [node, READ_WEB, phir], [node, WEB_MAIN, phir, "--run"]


def measure_program(path: str, m: Measurer, vm: str, node: str, v1_phir: str,
                    log) -> dict:
    name = os.path.basename(path)
    stem = os.path.splitext(name)[0]
    folder = os.path.join(WORK, "programs", stem)
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    shutil.copy(path, folder)
    with open(os.path.join(folder, ".suriaX_config.yaml"), "w", encoding="utf-8") as fh:
        fh.write(CONFIG_YAML)
    log(f"== {name}")
    res: dict = {"program": name}

    # cada HIR en su carpeta, con SUS unidades de librería al lado
    dirs = {h: os.path.join(folder, h) for h in HIRS}
    out = {h: os.path.join(h, name + ".phir") for h in HIRS}
    cmds = {
        "s1": [sys.executable, V0_MAIN, name, "--emit-hir", out["s1"], "--hir-schema", "1"],
        "s2": [sys.executable, V0_MAIN, name, "--emit-hir", out["s2"], "--hir-schema", "2"],
        "v1": [vm, v1_phir, "--run", "--quiet", "--pasos", "0", "--",
               name, out["v1"], "--stdlib", STDLIB],
    }
    res["emit"] = {}
    for h in HIRS:
        res["emit"][h] = m.measure(f"emisión {HIR_SHORT[h]}", cmds[h], folder,
                                   prepare=lambda d=dirs[h]: shutil.rmtree(d, ignore_errors=True))
    files = {h: unit_files(dirs[h]) for h in HIRS}
    res["ok_emit"] = {h: res["emit"][h]["rc"] == 0 and os.path.isfile(os.path.join(folder, out[h]))
                      for h in HIRS}
    res["sizes"] = {h: sizes(files[h], name + ".phir") if res["ok_emit"][h] else None
                    for h in HIRS}
    # compiladores: el .phir de la V0 (esquema 2, el de hoy) contra el de la V1
    res["compiler_equal"] = (compare_units(files["s2"], files["v1"])
                             if res["ok_emit"]["s2"] and res["ok_emit"]["v1"] else None)

    res["cells"] = {}
    for h in HIRS:
        if not res["ok_emit"][h]:
            log(f"    ({HIR_SHORT[h]}: no hay .phir; sus celdas no se miden)")
            continue
        for t in TARGETS:
            read_cmd, exec_cmd = target_cmds(t, out[h], vm, node)
            res["cells"][f"{h}/{t}"] = {
                "read": m.measure(f"lectura {h}/{t}", read_cmd, folder),
                "exec": m.measure(f"ejecución {h}/{t}", exec_cmd, folder)}

    ref = res["cells"].get(f"{REF_HIR}/interp", {}).get("exec")
    expected_path = os.path.splitext(path)[0] + ".expected"
    want = None
    if os.path.isfile(expected_path):
        with open(expected_path, "rb") as fh:
            want = lf(fh.read())
        res["expected_file"] = os.path.relpath(expected_path, REPO).replace("\\", "/")
    for key, cell in res["cells"].items():
        e = cell["exec"]
        cell["cmp"] = None if ref is None else {
            "stdout_bytes": e["stdout"] == ref["stdout"],
            "stdout_lf": lf(e["stdout"]) == lf(ref["stdout"]),
            "stderr_bytes": e["stderr"] == ref["stderr"],
            "stderr_lf_no_banner": no_banner(e["stderr"]) == no_banner(ref["stderr"]),
            "rc_equal": e["rc"] == ref["rc"],
            "ref_rc": ref["rc"],
            "ref_stdout_lines": lf(ref["stdout"]).count(b"\n"),
            "common_prefix_lines": common_prefix_lines(lf(e["stdout"]), lf(ref["stdout"])),
            "expected": None if want is None else lf(e["stdout"]) == want,
        }
    return res


# --------------------------------------------------------------------------
# clasificación: OK / NOT SUPPORTED / ERROR
# --------------------------------------------------------------------------

def text_of(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def codes(err: bytes, prefix: str) -> list:
    return sorted(set(re.findall(r"\b(" + prefix + r"\d{3})\b", text_of(err))))


def first_lines(data: bytes, n: int = 3, width: int = 160) -> str:
    lines = [ln.strip() for ln in text_of(data).splitlines() if ln.strip()]
    out = [ln if len(ln) <= width else ln[:width] + "…" for ln in lines[:n]]
    return " ⏎ ".join(out).replace("|", "\\|")


def emit_status(res: dict, h: str) -> tuple:
    """Estado de una EMISIÓN: ('OK'|'NOT SUPPORTED'|'ERROR', detalle)."""
    e = res["emit"][h]
    if res["ok_emit"][h]:
        return "OK", ""
    err = text_of(e["stderr"])
    # un rechazo explícito: diagnósticos con código y posición, salida 1
    diag = re.findall(r":\d+:\d+: ([A-Z]{2,4}\d{3})", err)
    if e["rc"] == 1 and (diag or "todavía no compila" in err):
        return "NOT SUPPORTED", ", ".join(sorted(set(diag))) or "la V1 todavía no compila"
    return "ERROR", f"código {e['rc']}: `{first_lines(e['stdout'] + e['stderr'], 3)}`"


def cell_status(res: dict, key: str) -> tuple:
    """Estado de una celda HIR × target, con su detalle (lo que se midió)."""
    cell = res["cells"][key]
    e, c = cell["exec"], cell["cmp"]
    err = text_of(e["stderr"])
    if "rechazó el programa" in err:
        return "NOT SUPPORTED", "web: " + ", ".join(codes(e["stderr"], "WEB"))
    vm_codes = codes(e["stderr"], "VM")
    if key.endswith("/vm") and vm_codes and e["rc"] != 0 and c and not c["rc_equal"]:
        return "NOT SUPPORTED", "VM: " + ", ".join(vm_codes)
    if c is None:
        return "ERROR", "no hay referencia (el intérprete con el esquema 2 no corrió)"
    problems = []
    if "RuntimeError:" in err:
        msg = re.search(r"RuntimeError: ([^\r\n]*)", err)
        whole = min(c["common_prefix_lines"], c["ref_stdout_lines"])
        problems.append(f"trap de wasm sin traducir (`RuntimeError: {msg.group(1) if msg else '?'}`); "
                        f"antes imprime iguales {whole} de {c['ref_stdout_lines']} líneas")
    elif not c["stdout_lf"]:
        problems.append(f"stdout distinta (coinciden {c['common_prefix_lines']} líneas)")
    if not c["rc_equal"]:
        problems.append(f"código {e['rc']} en vez de {c['ref_rc']}")
    if c["expected"] is False and c["stdout_lf"]:
        problems.append("la salida no es la esperada por la semántica documentada")
    if not cell["exec"]["deterministic"] or not cell["read"]["deterministic"]:
        problems.append("salida distinta entre corridas")
    if problems:
        return "ERROR", "; ".join(problems)
    notes = []
    if not c["stdout_bytes"]:
        notes.append("`\\n` en vez de `\\r\\n`")
    if not c["stderr_bytes"]:
        notes.append("marca `[wasm] main() -> N` en stderr" if c["stderr_lf_no_banner"]
                     else f"otro texto en stderr: `{first_lines(e['stderr'], 1, 120)}`")
    return "OK", ("formato: " + "; ".join(notes)) if notes else ""


def badge(status: str, detail: str) -> str:
    if status == "OK":
        return "OK" + (f" ({detail})" if detail else "")
    return f"**{status}** ({detail})"


#: Explicaciones de causa. Cada una solo aparece si la EVIDENCIA (un texto de la
#: salida medida) está; lo que digan más allá de esa evidencia es INFERIDO y lo
#: dicen.
def known_causes(res: dict) -> list:
    out = []
    def any_web(text: str) -> bool:
        return any(text in text_of(c["exec"]["stderr"])
                   for k, c in res["cells"].items() if k.endswith("/web"))
    v1err = res["emit"]["v1"]["stderr"]
    if not res["ok_emit"]["v1"] and b"vector.libsrx" in v1err:
        out.append(("NOT SUPPORTED", "La V1 no compila `lib/array/vector.libsrx` de hoy: su "
                    "parser no acepta la cota `T: Ord` ni los tipos función `fn(...) -> ...`. "
                    "Medido: " + library_lines(v1err, "array", "vector.libsrx")))
    if any_web("WEB002") and any_web("vector.libsrx"):
        k = next(k for k in res["cells"] if k.endswith("/web"))
        out.append(("NOT SUPPORTED", "El web rechaza `Vector`: su implementación usa punteros "
                    "(WEB002, WEB003), `move` (WEB006) y funciones como valores (WEB103). "
                    "Medido: códigos " + ", ".join(codes(res["cells"][k]["exec"]["stderr"], "WEB"))
                    + ", el primero en `<stdlib>/array/vector.libsrx`."))
    if (any_web("WEB100") or any_web("WEB101")) and any_web("Punto"):
        out.append(("NOT SUPPORTED", "El codegen web no representa structs (WEB100/WEB101: "
                    "\"un struct o un puntero, no\"). Medido en el diagnóstico."))
    if any_web("divide by zero"):
        out.append(("ERROR", "División entera por cero: en wasm es un trap; el web no lo "
                    "convierte en `EXC001` (código 70) como el intérprete y la VM, y node "
                    "sale con 1 y su pila. Medido: mensaje y código. Inferido: el codegen "
                    "emite `i64.div_s` sin comprobar el divisor."))
    if any_web("divide result unrepresentable"):
        out.append(("ERROR", "`MIN / -1`: en wasm es un trap; el intérprete y la VM ENVUELVEN "
                    "y dan `MIN`, como manda la documentación. Medido: el mensaje del trap. "
                    "Inferido: el codegen emite `i64.div_s` sin el caso especial."))
    return out


def library_lines(err: bytes, package: str, filename: str) -> str:
    """Cada '<filename>:L:C: CÓDIGO' del stderr, con la línea L citada."""
    path = os.path.join(STDLIB, package, filename)
    try:
        with open(path, encoding="utf-8") as fh:
            source = fh.read().splitlines()
    except OSError:
        source = []
    found = []
    pattern = re.escape(filename) + r":(\d+):(\d+): (\w+)"
    for ln, col, code in re.findall(pattern, text_of(err)):
        text = source[int(ln) - 1].strip() if 0 < int(ln) <= len(source) else "?"
        found.append(f"{code} en {ln}:{col} (`{text}`)")
    return "; ".join(found) or "(sin posiciones en el mensaje)"


def compiler_difference(res: dict) -> str:
    """Dónde difieren el .phir de la V0 y el de la V1 (mismo esquema 2)."""
    folder = os.path.join(WORK, "programs", os.path.splitext(res["program"])[0])
    name = res["program"] + ".phir"
    a_path, b_path = os.path.join(folder, "s2", name), os.path.join(folder, "v1", name)
    try:
        with open(a_path, "rb") as fa, open(b_path, "rb") as fb:
            a, b = fa.read(), fb.read()
    except OSError:
        return ""
    if a == b:
        return ""
    byte = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    views = []
    for p in (a_path, b_path):
        r = subprocess.run([sys.executable, INTERP_MAIN, p, "--text"], capture_output=True,
                           env=child_env(), timeout=600)
        views.append(text_of(r.stdout).splitlines())
    diffs = [(i, x.strip(), y.strip()) for i, (x, y) in enumerate(zip(*views)) if x != y]
    detail = ", ".join(f"`{x}` (V0) contra `{y}` (V1)" for _, x, y in diffs[:3])
    text = (f"primer byte distinto: {byte} (de {len(a)} y {len(b)} B); en la vista `--text` "
            f"difieren {len(diffs)} líneas, p. ej. {detail}")
    if diffs and len(views[0]) == len(views[1]) and \
            all(x.startswith("col:") and y.startswith("col:") for _, x, y in diffs):
        lines = sorted({next((v.split(":")[1].strip() for v in reversed(views[0][:i])
                              if v.strip().startswith("ln:")), "?") for i, _, _ in diffs},
                       key=lambda t: int(t) if t.isdigit() else 0)
        text += (f". Medido: TODAS son columnas (`col`), en las líneas {', '.join(lines)} "
                 "del fuente (todas con f-strings); el árbol es el mismo. Reproducción "
                 "mínima en el README §10")
    return text


# --------------------------------------------------------------------------
# informe
# --------------------------------------------------------------------------

def fnum(x: float) -> str:
    return f"{x:.0f}" if x >= 100 else f"{x:.1f}"


def fmt_ms(st: dict) -> str:
    if not st:
        return "—"
    return (f"**{fnum(st['median_ms'])}** [{fnum(st['min_ms'])}–{fnum(st['max_ms'])}] "
            f"RIC {fnum(st['q3_ms'] - st['q1_ms'])}")


def yn(v) -> str:
    return "—" if v is None else ("sí" if v else "**NO**")


def compare_times(a: dict, b: dict) -> tuple:
    """(texto, veredicto) de pasar de ``a`` (esquema 1) a ``b`` (esquema 2).
    Veredicto: 'mejor', 'peor' o 'ruido'. El criterio es simple y se declara
    en el informe: si los rangos intercuartílicos [Q1, Q3] se solapan, la
    diferencia no se distingue del ruido de esta máquina."""
    if not a or not b:
        return "—", None
    ma, mb = a["median_ms"], b["median_ms"]
    pct = (mb - ma) / ma * 100 if ma else 0.0
    overlap = not (b["q3_ms"] < a["q1_ms"] or a["q3_ms"] < b["q1_ms"])
    verdict = "ruido" if overlap else ("mejor" if mb < ma else "peor")
    tag = {"ruido": "dentro del ruido", "mejor": "**mejor**", "peor": "**peor**"}[verdict]
    return (f"{fnum(ma)} → {fnum(mb)} ms ({pct:+.1f} %; RIC {fnum(a['q3_ms'] - a['q1_ms'])} / "
            f"{fnum(b['q3_ms'] - b['q1_ms'])}) {tag}"), verdict


def pct(a, b) -> str:
    if not a or b is None:
        return "—"
    return f"{(b - a) / a * 100:+.1f} %"


def render(results: dict, path_md: str) -> None:
    env = results["environment"]
    progs = results["programs"]
    out: list = []
    w = out.append

    # ---- recuentos -----------------------------------------------------
    counts = {h: {"OK": 0, "NOT SUPPORTED": 0, "ERROR": 0} for h in HIRS}
    emit_counts = {h: {"OK": 0, "NOT SUPPORTED": 0, "ERROR": 0} for h in HIRS}
    for p in progs:
        for h in HIRS:
            st, _ = emit_status(p, h)
            emit_counts[h][st] += 1
            for t in TARGETS:
                key = f"{h}/{t}"
                if key in p["cells"]:
                    st2, _ = cell_status(p, key)
                else:
                    st2 = "NOT SUPPORTED" if st == "NOT SUPPORTED" else "ERROR"
                counts[h][st2] += 1

    w(f"# Diferencial de suriaX {env.get('suriax_version') or suriax_version()}: "
      "esquema 1 frente a 2 del HIR, y compilador V0 frente a V1\n")
    w("> Generado por `dev/diff/run_diff.py`; no editar a mano. Cómo replicarlo: "
      "[README.md](README.md). Datos crudos: [results.json](results.json).\n")
    w("Hay DOS comparaciones distintas, y no hay que confundirlas:\n")
    w("1. **Esquema 1 frente a esquema 2 del HIR** (la principal). El mismo compilador "
      "(la V0) emite el `.phir` con `--hir-schema 1` (el esquema inicial: cada tipo "
      "escrito inline en su nodo) y con `--hir-schema 2` (el de hoy: un pool de tipos, "
      "`Module.types`, y los nodos con un índice). Los tres targets leen y ejecutan los "
      "dos. Ver [schema/README.md](schema/README.md).")
    w("2. **Compilador V0 frente a compilador V1** (apartado aparte). La V0 (Python) y la V1 "
      "(escrita en suriaX, corriendo en la VM) compilan el mismo programa, las dos al "
      "esquema 2, y se compara su `.phir` byte a byte y su ejecución.\n")
    w("Cada celda es **OK** (misma salida, tras normalizar el fin de línea, y mismo código "
      "que la referencia), **NOT SUPPORTED** (un compilador o un target RECHAZA de forma "
      "explícita algo que aún no soporta, con su código: `WEBxxx`, `VMxxx`, o la V1 con "
      "un error de sintaxis que no conoce) o **ERROR** (una divergencia de verdad al "
      "ejecutar: un trap, otra salida, otro código, o una salida que no es la que exige "
      "la semántica documentada). La **referencia** es el intérprete ejecutando el HIR "
      "del esquema 2 emitido por la V0.\n")

    w("## Resumen\n")
    w("### Recuento de celdas (HIR × target)\n")
    w("| HIR | OK | NOT SUPPORTED | ERROR | Emisión: OK / NOT SUPPORTED / ERROR |\n"
      "|---|---|---|---|---|")
    tot = {"OK": 0, "NOT SUPPORTED": 0, "ERROR": 0}
    for h in HIRS:
        c, ec = counts[h], emit_counts[h]
        for k in tot:
            tot[k] += c[k]
        w(f"| {HIR_NAMES[h]} | {c['OK']} | {c['NOT SUPPORTED']} | {c['ERROR']} | "
          f"{ec['OK']} / {ec['NOT SUPPORTED']} / {ec['ERROR']} |")
    w(f"| **Total** | **{tot['OK']}** | **{tot['NOT SUPPORTED']}** | **{tot['ERROR']}** | |")
    w("")
    w(f"{len(progs)} programas × 3 targets por HIR. Cuando un compilador no emite (NOT "
      "SUPPORTED), sus tres celdas cuentan con el mismo estado.\n")

    # ---- resumen del esquema ------------------------------------------
    w("### Esquema 2 frente a esquema 1 (compilador V0)\n")
    w("Cambio al pasar del esquema 1 al 2. Tamaño: negativo = el 2 ocupa menos. Tiempos: "
      "mediana del 1 → mediana del 2, el cambio relativo y los RIC de cada uno. "
      "**Criterio de ruido** (simple, no es una prueba estadística): si los rangos "
      "intercuartílicos [Q1, Q3] de los dos se solapan, la diferencia se marca "
      "\"dentro del ruido\".\n")
    w("| Programa | `.phir` del programa (1 → 2) | Todas las unidades (1 → 2) | Emisión |\n"
      "|---|---|---|---|")
    size_main, size_all = [], []
    verdicts = {}
    for p in progs:
        s1, s2 = p["sizes"]["s1"], p["sizes"]["s2"]
        if s1 and s2:
            size_main.append(s2["main_bytes"] / s1["main_bytes"])
            size_all.append(s2["all_units_bytes"] / s1["all_units_bytes"])
            em, v = compare_times(p["emit"]["s1"]["stats"], p["emit"]["s2"]["stats"])
            verdicts.setdefault("emisión", []).append(v)
            w(f"| `{p['program']}` | {s1['main_bytes']} → {s2['main_bytes']} B "
              f"({pct(s1['main_bytes'], s2['main_bytes'])}) | {s1['all_units_bytes']} → "
              f"{s2['all_units_bytes']} B ({pct(s1['all_units_bytes'], s2['all_units_bytes'])}) "
              f"| {em} |")
    w("")
    if size_main:
        w(f"Tamaño (medido, es exacto, sin ruido): el `.phir` del programa ocupa con el esquema "
          f"2 entre el {min(size_main) * 100:.0f} % y el {max(size_main) * 100:.0f} % del "
          f"esquema 1 (mediana {statistics.median(size_main) * 100:.0f} %); contando todas "
          f"las unidades, entre el {min(size_all) * 100:.0f} % y el "
          f"{max(size_all) * 100:.0f} % (mediana {statistics.median(size_all) * 100:.0f} %).\n")
    for what, label in (("read", "Lectura"), ("exec", "Ejecución")):
        w(f"**{label}** (ms), esquema 1 → 2:\n")
        w("| Programa | " + " | ".join(TARGET_NAMES[t] for t in TARGETS) + " |\n|---|---|---|---|")
        for p in progs:
            row = []
            for t in TARGETS:
                a = p["cells"].get(f"s1/{t}")
                b = p["cells"].get(f"s2/{t}")
                if not a or not b:
                    row.append("—")
                    continue
                sa, _ = cell_status(p, f"s1/{t}")
                sb, _ = cell_status(p, f"s2/{t}")
                text, v = compare_times(a[what]["stats"], b[what]["stats"])
                if sa == "NOT SUPPORTED" or sb == "NOT SUPPORTED":
                    text += " — rechazado"
                else:
                    verdicts.setdefault(f"{label.lower()} {t}", []).append(v)
                row.append(text)
            w(f"| `{p['program']}` | " + " | ".join(row) + " |")
        w("")
    w("**En cuántos programas el esquema 2 es mejor, peor o no se distingue** (las celdas "
      "rechazadas no cuentan):\n")
    w("| Medida | mejor | peor | dentro del ruido |\n|---|---|---|---|")
    for k, vs in verdicts.items():
        w(f"| {k} | {vs.count('mejor')} | {vs.count('peor')} | {vs.count('ruido')} |")
    w("")

    # ---- entorno y método ---------------------------------------------
    w("## Entorno\n")
    w("| | |\n|---|---|")
    w(f"| Versión de suriaX (`version.py`) | {env.get('suriax_version') or suriax_version()} |")
    w(f"| Fecha | {env['date']} |")
    w(f"| SO | {env['os']} |")
    w(f"| CPU | {env['cpu']} ({env['logical_cpus']} núcleos lógicos) |")
    w(f"| Carga de la CPU | antes: {env['load_before']}; después: {env.get('load_after', '?')} |")
    w(f"| Python | {env['python']} |")
    w(f"| node | {env['node']} |")
    w(f"| pyyaml (lo usa la V0 para leer `.suriaX_config.yaml`) | {env.get('pyyaml', '?')} |")
    w(f"| Compilador C++ (VM) | {env['cxx']} |")
    w(f"| VM | {env['vm_binary']} |")
    dirty = (f" + **{env['dirty_files']} archivos con cambios sin commit** "
             f"(sha256 de `git diff HEAD`: {env['diff_sha256']}…)") if env["dirty_files"] else ""
    w(f"| Commit | `{env['commit']}`{dirty} |")
    w(f"| Reloj | `time.perf_counter_ns` — {env['clock']} |")
    w(f"| Repeticiones | {results['reps']} por medida, la 1.ª descartada (calentamiento); "
      f"presupuesto por celda {results['cell_budget_s']:.0f} s |")
    w(f"| Duración de la corrida | {results['duration_s'] / 60:.1f} min |")
    w("")
    w("## Cómo se mide\n")
    w("- Tiempos en **milisegundos de pared** por corrida, medidos por el arnés alrededor "
      "del proceso hijo: **mediana** [mínimo–máximo] y RIC (Q3 − Q1) de las corridas que "
      "quedan tras descartar la primera.")
    w("- **Emisión**: esquema 1: `python V0/main.py prog.srcx --emit-hir s1/prog.srcx.phir "
      "--hir-schema 1`; esquema 2: lo mismo con `s2/` y `--hir-schema 2`; compilador V1: "
      "`suriax-hir work/v1/dumps/main.srcx.phir --run --quiet --pasos 0 -- prog.srcx "
      "v1/prog.srcx.phir --stdlib <repo>/lib`. Los tres emiten el `.phir` del programa Y el "
      "de cada librería en su carpeta, y cada HIR se ejecuta con SUS unidades.")
    w("- **Lectura** (cargar, decodificar y ligar, sin ejecutar): intérprete `python "
      "dev/diff/read_interp.py x.phir`; VM `suriax-hir x.phir --link`; web `node "
      "dev/diff/read_web.ts x.phir`. Con el esquema 1, la lectura incluye normalizarlo al "
      "pool de tipos.")
    w("- **Ejecución**: intérprete `python runtime/interpreter/main.py x.phir --exec`; VM "
      "`suriax-hir x.phir --run --quiet` (incluye leer, resolver, bajar a MIR y "
      "verificar); web `node web/main.ts x.phir --run` (incluye leer, contener, DCE, "
      "generar el WebAssembly y ejecutarlo).")
    w("- **Tamaño**: el `.phir` del programa / la suma de todas las unidades.\n")
    base = results.get("baselines")
    if base:
        w("Lo que cuesta solo ARRANCAR cada proceso (incluido en todos los tiempos):\n")
        w("| Proceso | Comando | Tiempo (ms) |\n|---|---|---|")
        for k, b in base.items():
            cmd = " ".join(os.path.basename(c) if i == 0 else c for i, c in enumerate(b["cmd"]))
            w(f"| {k} | `{cmd}` | {fmt_ms(b['stats'])} |")
        w("")

    # ---- detalle por programa: esquemas --------------------------------
    reductions: list = []
    findings: list = []      # (estado, programa, dónde, detalle)

    def collect(p: dict) -> None:
        for h in HIRS:
            st, d = emit_status(p, h)
            if st != "OK":
                findings.append((st, p["program"], f"emisión {HIR_SHORT[h]}", d + (
                    f": `{first_lines(p['emit'][h]['stderr'], 4, 260)}`" if st == "NOT SUPPORTED" else "")))
            if p["emit"][h]["reduced"]:
                reductions.append(f"`{p['program']}` emisión {HIR_SHORT[h]}: {p['emit'][h]['reduced']}")
        for key in p["cells"]:
            st, d = cell_status(p, key)
            if st != "OK":
                findings.append((st, p["program"], f"{HIR_SHORT[key.split('/')[0]]} × {TARGET_NAMES[key.split('/')[1]]}", d))
            for what in ("read", "exec"):
                if p["cells"][key][what]["reduced"]:
                    reductions.append(f"`{p['program']}` {key} {what}: {p['cells'][key][what]['reduced']}")
        for st, text in known_causes(p):
            findings.append((st, p["program"], "causa", text))
        ce = p["compiler_equal"]
        if ce is not None and not ce["all_equal"]:
            findings.append(("ERROR", p["program"], "compilador V0 frente a V1",
                             f"`.phir` distintos ({', '.join(ce['differ'])}): "
                             + compiler_difference(p)))

    def cells_table(p: dict, hirs: tuple) -> None:
        w("| HIR | Target | Lectura (ms) | Ejecución (ms) | Estado | Código |\n"
          "|---|---|---|---|---|---|")
        for h in hirs:
            for t in TARGETS:
                key = f"{h}/{t}"
                if key not in p["cells"]:
                    st, d = emit_status(p, h)
                    w(f"| {HIR_SHORT[h]} | {TARGET_NAMES[t]} | — | — | "
                      f"{badge(st, 'no hay `.phir`: ' + d)} | — |")
                    continue
                cell = p["cells"][key]
                st, d = cell_status(p, key)
                w(f"| {HIR_SHORT[h]} | {TARGET_NAMES[t]} | {fmt_ms(cell['read']['stats'])} | "
                  f"{fmt_ms(cell['exec']['stats'])} | {badge(st, d)} | {cell['exec']['rc']} |")
        w("")

    def reference_output(p: dict) -> None:
        ref = p["cells"].get(f"{REF_HIR}/interp", {}).get("exec")
        if ref is None:
            return
        lines = text_of(lf(ref["stdout"])).splitlines()
        shown = "\n".join(lines[:30]) + (f"\n… ({len(lines) - 30} líneas más)" if len(lines) > 30 else "")
        w("<details><summary>Salida de referencia (intérprete, esquema 2)"
          + (" y stderr" if ref["stderr"] else "") + "</summary>\n")
        w("```text\n" + shown + "\n```")
        if ref["stderr"]:
            w("\n```text\n" + text_of(lf(ref["stderr"])).strip() + "\n```")
        w("\n</details>\n")

    def sz(s):
        return "—" if not s else f"{s['main_bytes']} / {s['all_units_bytes']} B ({s['units']} unidades)"

    for p in progs:
        collect(p)

    normal = [p for p in progs if not p["program"].startswith("06_sintetico")]
    synth = [p for p in progs if p["program"].startswith("06_sintetico")]

    w("## 1. Esquema 1 frente a esquema 2: detalle por programa\n")
    for p in normal + synth:
        w(f"### `{p['program']}`\n")
        w("| | Esquema 1 | Esquema 2 |\n|---|---|---|")
        w(f"| Emisión (ms) | {fmt_ms(p['emit']['s1']['stats'])} | {fmt_ms(p['emit']['s2']['stats'])} |")
        w(f"| Tamaño `.phir` (programa / todas) | {sz(p['sizes']['s1'])} | {sz(p['sizes']['s2'])} |")
        w("")
        cells_table(p, ("s1", "s2"))
        if "expected_file" in p:
            w(f"Salida esperada por la semántica documentada: `{p['expected_file']}` (cuenta "
              "en el estado: si no coincide, la celda es ERROR).\n")
        reference_output(p)

    if synth:
        w("### Los sintéticos, de un vistazo\n")
        w("Generados por `dev/diff/gen_synthetic.py` (semilla fija): funciones de ~40 "
          "sentencias con int, float, bool, str, char y un enum sin datos; aritmética, "
          "comparaciones, `if`, `while`, llamadas, `match` y `println` de resultados "
          "intermedios. **Sin structs**, porque el web los rechaza (ver `09_structs.srcx`).\n")
        w("| Sentencias | Fuente | `.phir` esq. 1 → 2 | Emisión esq. 1 → 2 (ms) | "
          + " | ".join(f"Ejecución {TARGET_NAMES[t]} esq. 1 → 2 (ms)" for t in TARGETS) + " |")
        w("|---|---|---|---|---|---|---|")
        for p in synth:
            n = re.search(r"_(\d+)\.srcx$", p["program"]).group(1)
            src = os.path.getsize(os.path.join(PROGRAMS_DIR, p["program"]))
            s1, s2 = p["sizes"]["s1"], p["sizes"]["s2"]
            row = [n, f"{src} B",
                   f"{s1['main_bytes']} → {s2['main_bytes']} B ({pct(s1['main_bytes'], s2['main_bytes'])})"
                   if s1 and s2 else "—",
                   f"{fnum(p['emit']['s1']['stats']['median_ms'])} → "
                   f"{fnum(p['emit']['s2']['stats']['median_ms'])}"]
            for t in TARGETS:
                a, b = p["cells"].get(f"s1/{t}"), p["cells"].get(f"s2/{t}")
                row.append("—" if not a or not b else
                           f"{fnum(a['exec']['stats']['median_ms'])} → {fnum(b['exec']['stats']['median_ms'])}")
            w("| " + " | ".join(row) + " |")
        w("")

    # ---- compiladores --------------------------------------------------
    w("## 2. Compilador V0 frente a compilador V1\n")
    w("Los dos emiten el esquema 2. \"Compilador V0\" es el `.phir` del esquema 2 de la "
      "sección anterior; \"compilador V1\" es el que emite la V1 corriendo en la VM, "
      "ejecutado con las unidades de librería que emitió ella misma.\n")
    w("| Programa | Emisión V0 (ms) | Emisión V1 (ms) | Estado de la emisión V1 | `.phir` V0 = V1 "
      "(byte a byte) | Celdas del compilador V1 (OK / NS / ERROR) |\n|---|---|---|---|---|---|")
    for p in progs:
        st, d = emit_status(p, "v1")
        ce = p["compiler_equal"]
        eq = ("—" if ce is None else
              (f"sí ({len(ce['same'])}/{len(ce['same'])} unidades)" if ce["all_equal"]
               else f"**NO** ({', '.join(ce['differ'])})"))
        cc = {"OK": 0, "NOT SUPPORTED": 0, "ERROR": 0}
        for t in TARGETS:
            key = f"v1/{t}"
            cc[cell_status(p, key)[0] if key in p["cells"] else st] += 1
        w(f"| `{p['program']}` | {fmt_ms(p['emit']['s2']['stats'])} | "
          f"{fmt_ms(p['emit']['v1']['stats'])} | {badge(st, d)} | {eq} | "
          f"{cc['OK']} / {cc['NOT SUPPORTED']} / {cc['ERROR']} |")
    w("")
    w("Detalle de las celdas del compilador V1 (lectura y ejecución de su `.phir`):\n")
    for p in progs:
        w(f"#### `{p['program']}`\n")
        cells_table(p, ("v1",))

    # ---- hallazgos -----------------------------------------------------
    w("## NOT SUPPORTED y ERROR: qué y por qué\n")
    w("Todo sale de la salida capturada (medido). Donde una causa va más allá de la "
      "salida, su texto dice qué parte es inferida.\n")
    for status in ("ERROR", "NOT SUPPORTED"):
        rows = [f for f in findings if f[0] == status]
        w(f"### {status} ({sum(1 for f in rows if f[2] != 'causa')} celdas, emisiones o comparaciones de compiladores)\n")
        if not rows:
            w("Ninguno.\n")
            continue
        w("| Programa | Dónde | Detalle / causa |\n|---|---|---|")
        seen = set()
        for _, prog, where, detail in sorted(rows, key=lambda f: (f[1], f[2] == "causa", f[2])):
            if (prog, where, detail) in seen:
                continue
            seen.add((prog, where, detail))
            w(f"| `{prog}` | {where} | {detail} |")
        w("")
    w("Diferencias que NO cuentan como error (la celda es OK y se anota en ella): en "
      "Windows el intérprete y la VM escriben `\\r\\n` y node `\\n`; el CLI del web "
      "escribe `[wasm] main() -> N` en stderr; ante un error de ejecución, la VM antepone "
      "`error de ejecucion: ` al mensaje del intérprete.\n")

    w("## Reducciones de repeticiones\n")
    w("\n".join(f"- {r}" for r in reductions) if reductions
      else "Ninguna: todas las celdas hicieron las corridas pedidas.")
    w("")
    w("## Límites de la medición\n")
    for item in limits(env):
        w(f"- {item}")
    w("")
    with open(path_md, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(sanitize("\n".join(out)))


def limits(env: dict) -> list:
    return [
        "**Cada tiempo incluye arrancar el proceso** (Python, node o la VM; ver la línea "
        "base). En programas pequeños el arranque domina, y eso diluye cualquier diferencia "
        "entre esquemas: el cambio de esquema solo afecta a leer el `.phir`, no a arrancar.",
        "La **lectura** es la operación más cercana a \"solo cargar\" que expone cada "
        "target, pero no son idénticas (la VM con `--link` además imprime las unidades).",
        "La **ejecución** del web incluye generar el WebAssembly; la de la VM, bajar a MIR "
        "y verificar; la del intérprete, ligar las unidades. Los CLI no permiten separarlo.",
        "El **criterio de ruido** (solapamiento de los RIC) es una regla simple, no una "
        "prueba de hipótesis; con 29 muestras por lado y sin aislamiento de CPU, "
        "diferencias de pocos por ciento no se pueden afirmar.",
        f"Resolución del reloj: {env['clock']}; mucho más fina que los tiempos medidos.",
        f"**Sin aislamiento de CPU** (ni afinidad, ni prioridad, ni frecuencia fija). "
        f"{env['logical_cpus']} núcleos lógicos, en uso normal (carga antes: "
        f"{env['load_before']}; después: {env.get('load_after', '?')}). En la corrida "
        "publicada había **carga de fondo**: otro agente trabajando en paralelo y "
        "procesos del mantenedor (un servidor de lenguaje `--lsp` y "
        "`playground/server.py`). Corridas secuenciales; cada "
        "celda hace sus corridas seguidas, sin intercalar, así que una deriva lenta afecta "
        "más a unas celdas que a otras.",
        "Se descarta la primera corrida de cada medida (caché de disco, `.pyc`).",
        "El esquema 1 que se mide es el **adaptado a hoy** (`--hir-schema 1`), no un "
        "`.phir` escrito por el compilador de agosto de 2026: ver `schema/README.md`.",
        "Salidas capturadas por tubería. En Linux las tres escribirían `\\n`.",
        "El web corre en node (V8), no en un navegador. Un solo equipo, una sola corrida.",
        "Que los targets coincidan con la referencia dice que son CONSISTENTES; para 02 y "
        "08 hay además una salida esperada (`.expected`) calculada aparte con la semántica "
        "documentada (dividir truncando hacia cero, envolver a 64 bits).",
    ]


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def to_json(obj):
    if isinstance(obj, bytes):
        text = sanitize(obj.decode("utf-8", "replace"))
        return text if len(text) <= 200_000 else text[:200_000] + "\n[… truncado]"
    if isinstance(obj, str):
        return sanitize(obj)
    if isinstance(obj, dict):
        return {k: to_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_json(v) for v in obj]
    return obj


def from_json(obj, key: str = ""):
    """Inversa de :func:`to_json` para lo que usa el informe: las salidas
    vuelven a ser bytes (UTF-8; lo truncado sigue truncado)."""
    if isinstance(obj, dict):
        return {k: from_json(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [from_json(v) for v in obj]
    if key in ("stdout", "stderr") and isinstance(obj, str):
        return obj.encode("utf-8")
    return obj


def main() -> int:
    ap = argparse.ArgumentParser(description="Diferencial de suriaX (dev/diff).")
    ap.add_argument("--reps", type=int, default=30,
                    help="corridas por medida, la 1.ª se descarta (por defecto 30)")
    ap.add_argument("--only", nargs="*", default=None,
                    help="solo los programas cuyo nombre contiene alguno de estos textos")
    ap.add_argument("--cell-budget", type=float, default=1200.0,
                    help="segundos máximos por celda antes de reducir sus repeticiones "
                         "(por defecto 1200 = 20 min)")
    ap.add_argument("--min-runs", type=int, default=4,
                    help="corridas mínimas de una celda reducida (por defecto 4: 1 + 3)")
    ap.add_argument("--timeout", type=float, default=3600.0,
                    help="segundos máximos de UNA corrida (por defecto 3600)")
    ap.add_argument("--vm", default=None, help="ruta de suriax-hir")
    ap.add_argument("--node", default=None, help="ruta de node")
    ap.add_argument("--out", default=HERE, help="carpeta de RESULTS.md y results.json")
    ap.add_argument("--render-only", action="store_true",
                    help="no mide: vuelve a escribir RESULTS.md desde el results.json "
                         "existente (p. ej. tras cambiar el texto del informe)")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if args.render_only:
        register_paths(find_vm(args.vm), find_node(args.node))
        with open(os.path.join(args.out, "results.json"), encoding="utf-8") as fh:
            results = from_json(json.load(fh))
        render(results, os.path.join(args.out, "RESULTS.md"))
        print("RESULTS.md reescrito desde results.json (sin medir)")
        return 0
    if args.reps < 2:
        ap.error("--reps tiene que ser >= 2 (la primera se descarta)")

    vm, node = find_vm(args.vm), find_node(args.node)
    register_paths(vm, node)
    os.makedirs(WORK, exist_ok=True)
    log_fh = open(os.path.join(WORK, "run.log"), "w", encoding="utf-8")

    def log(text: str) -> None:
        print(text, flush=True)
        log_fh.write(text + "\n")
        log_fh.flush()

    started = time.time()
    env = environment(vm, node)
    log(f"entorno: {json.dumps(env, ensure_ascii=False)}")
    v1_phir = build_v1(log)
    m = Measurer(args.reps, args.cell_budget, args.min_runs, args.timeout, log)
    baselines = {
        "Python": m.measure("arranque Python", [sys.executable, "-c", "pass"], WORK),
        "node": m.measure("arranque node", [node, "-e", "0"], WORK),
        "VM": m.measure("arranque VM", [vm, "--help"], WORK),
    }
    programs = sorted(f for f in os.listdir(PROGRAMS_DIR) if f.endswith(".srcx"))
    if args.only:
        programs = [p for p in programs if any(o in p for o in args.only)]
    results = {"reps": args.reps, "cell_budget_s": args.cell_budget, "environment": env,
               "baselines": baselines, "programs": []}
    for name in programs:
        results["programs"].append(
            measure_program(os.path.join(PROGRAMS_DIR, name), m, vm, node, v1_phir, log))
        # tras cada programa: una corrida interrumpida deja lo medido
        results["duration_s"] = time.time() - started
        env["load_after"] = cpu_load()
        with open(os.path.join(args.out, "results.json"), "w", encoding="utf-8") as fh:
            json.dump(to_json(results), fh, ensure_ascii=False, indent=1)
        render(results, os.path.join(args.out, "RESULTS.md"))
    log(f"listo en {(time.time() - started) / 60:.1f} min -> "
        f"{os.path.join(args.out, 'RESULTS.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
