"""C++: las C++ Core Guidelines medidas con clang-tidy (``.clang-tidy``) y el
análisis estático de cppcheck.

clang-tidy necesita saber cómo se compila cada archivo: lee el
``compile_commands.json`` de un build hecho con CMake y Ninja (``build``,
``build-msvc``...). Las cabeceras se revisan a través de los ``.cpp`` que las
incluyen; un hallazgo en una cabecera se cuenta UNA vez aunque la incluyan
varios.
"""

from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from common import (
    count_lines,
    CPP_DIRS,
    CPP_EXTENSIONS,
    ROOT,
    find_tool,
    iter_files,
    msvc_environment,
    percent,
    rel,
    run,
    tool_version,
)

_TIDY_LINE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):(?P<col>\d+): (?P<level>warning|error): "
    r"(?P<msg>.*?) \[(?P<check>[\w\-.,]+)\]$"
)


def find_compile_database(preferred: Optional[str] = None) -> Optional[str]:
    """La carpeta de build con ``compile_commands.json``: la pedida, o la
    primera de ``build`` / ``build-*`` (las instrumentadas al final)."""
    if preferred:
        path = preferred if os.path.isabs(preferred) else os.path.join(ROOT, preferred)
        return path if os.path.isfile(os.path.join(path, "compile_commands.json")) else None
    candidates = ["build"] + sorted(
        (d for d in os.listdir(ROOT) if d.startswith("build-")), key=lambda d: ("san" in d, d)
    )
    for name in candidates:
        if os.path.isfile(os.path.join(ROOT, name, "compile_commands.json")):
            return os.path.join(ROOT, name)
    return None


# --------------------------------------------------------------------------- #
# cppcheck
# --------------------------------------------------------------------------- #


def cppcheck() -> dict:
    """Errores, avisos, estilo, rendimiento y portabilidad según cppcheck."""
    exe = find_tool("cppcheck", "CPPCHECK")
    if exe is None:
        return {"measured": False, "reason": "cppcheck no está instalado (o CPPCHECK)"}
    files = iter_files(CPP_DIRS, CPP_EXTENSIONS)
    sources = [f for f in files if f.endswith((".cpp", ".cc", ".cxx"))]
    includes = [
        "-I",
        os.path.join(ROOT, "backend", "include"),
        "-I",
        os.path.join(ROOT, "runtime", "logic_mem", "include"),
        # lo define CMake (SuriaXBackend.cmake); sin él cppcheck ve un
        # error de sintaxis donde no lo hay
        '-DSURIAX_CXX_ESTANDAR="20"',
    ]
    # missingIncludeSystem: cppcheck no busca las cabeceras del sistema (no
    # las necesita para analizar); no es un hallazgo del proyecto
    out = run(
        [
            exe,
            "--enable=warning,style,performance,portability",
            "--std=c++20",
            "--language=c++",
            "--inline-suppr",
            "--suppress=missingIncludeSystem",
            "--xml",
            "--xml-version=2",
            "--quiet",
            *includes,
            *sources,
        ],
        timeout=7200,
    )
    try:
        root = ET.fromstring(out.stderr)
    except ET.ParseError:
        return {"measured": False, "reason": f"cppcheck no devolvió XML: {out.stderr[:300]}"}
    findings = []
    for error in root.iter("error"):
        location = error.find("location")
        if error.get("id") in ("checkersReport", "normalCheckLevelMaxBranches"):
            continue  # informativos de cppcheck, no hallazgos
        findings.append(
            {
                "id": error.get("id"),
                "severity": error.get("severity"),
                "message": error.get("msg"),
                "file": rel(location.get("file")) if location is not None else "",
                "line": int(location.get("line")) if location is not None else 0,
            }
        )
    files_rel = {rel(f) for f in files}
    lines = count_lines(files)
    return {
        "measured": True,
        "tool": tool_version([exe, "--version"]),
        "files": len(files),
        "lines": lines,
        "findings": len(findings),
        "per_kloc": round(1000 * len(findings) / lines, 2) if lines else None,
        "clean_files": len(files_rel - {f["file"] for f in findings}),
        "clean_files_pct": percent(len(files_rel - {f["file"] for f in findings}), len(files)),
        "by_severity": dict(Counter(f["severity"] for f in findings)),
        "by_id": dict(Counter(f["id"] for f in findings).most_common()),
        "items": findings,
    }


# --------------------------------------------------------------------------- #
# clang-tidy: C++ Core Guidelines
# --------------------------------------------------------------------------- #


def enabled_checks(exe: str) -> List[str]:
    """Las reglas que activa ``.clang-tidy`` (se listan contra un archivo
    del proyecto para que lea la configuración de la raíz)."""
    probe = os.path.join(ROOT, "backend", "src", "vm.cpp")
    out = run([exe, "--list-checks", probe, "--"])
    return sorted(
        line.strip()
        for line in out.stdout.splitlines()
        if line.startswith("    ") and line.strip()
    )


def clang_tidy(build_dir: Optional[str] = None, jobs: int = 0) -> dict:
    """Hallazgos de clang-tidy por regla, con el % de reglas de las Core
    Guidelines que el código cumple (cero hallazgos)."""
    exe = find_tool("clang-tidy", "CLANG_TIDY")
    if exe is None:
        return {"measured": False, "reason": "clang-tidy no está instalado (o CLANG_TIDY)"}
    database = find_compile_database(build_dir)
    if database is None:
        return {
            "measured": False,
            "reason": "no hay compile_commands.json: configura un build con CMake y "
            "Ninja (-G Ninja genera el archivo)",
        }
    with open(os.path.join(database, "compile_commands.json"), encoding="utf-8") as fh:
        entries = json.load(fh)
    units = sorted(
        {
            os.path.normpath(e["file"])
            for e in entries
            if rel(e["file"]).startswith(tuple(CPP_DIRS))
        }
    )
    env = msvc_environment()

    def one(unit: str) -> str:
        return run([exe, "-p", database, "--quiet", unit], env=env, timeout=3600).stdout

    with ThreadPoolExecutor(max_workers=jobs or min(8, os.cpu_count() or 2)) as pool:
        outputs = list(pool.map(one, units))
    seen = set()
    findings = []
    for text in outputs:
        for line in text.splitlines():
            m = _TIDY_LINE.match(line.strip())
            if not m:
                continue
            path = rel(m["file"])
            if not path.startswith(tuple(CPP_DIRS)):
                continue
            for check in m["check"].split(","):
                key = (path, int(m["line"]), int(m["col"]), check)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    {"file": path, "line": int(m["line"]), "check": check, "message": m["msg"]}
                )
    checks = enabled_checks(exe)
    guidelines = [c for c in checks if c.startswith("cppcoreguidelines-")]
    by_check = Counter(f["check"] for f in findings)
    violated = [c for c in guidelines if by_check.get(c)]
    files = iter_files(CPP_DIRS, CPP_EXTENSIONS)
    analyzed = {rel(f) for f in files} - {
        rel(f) for f in files if f.startswith(os.path.join(ROOT, "runtime"))
    }
    lines = count_lines([os.path.join(ROOT, f) for f in analyzed])
    core = [f for f in findings if f["check"].startswith("cppcoreguidelines-")]
    return {
        "measured": True,
        "tool": tool_version([exe, "--version"]).replace("LLVM (http://llvm.org/):", "").strip()
        or "clang-tidy",
        "compile_database": rel(database),
        "translation_units": [rel(u) for u in units],
        "files": len(analyzed),
        "lines": lines,
        "not_analyzed": sorted({rel(f) for f in files} - analyzed),
        "enabled_checks": len(checks),
        "core_guidelines": {
            "rules": len(guidelines),
            "rules_without_findings": len(guidelines) - len(violated),
            "rules_compliance_pct": percent(len(guidelines) - len(violated), len(guidelines)),
            "findings": len(core),
            "per_kloc": round(1000 * len(core) / lines, 2) if lines else None,
            "clean_files_pct": percent(len(analyzed - {f["file"] for f in core}), len(analyzed)),
            "violated_rules": {
                c: by_check[c] for c in sorted(violated, key=lambda c: -by_check[c])
            },
        },
        "other_groups": {
            group: sum(n for c, n in by_check.items() if c.startswith(group))
            for group in ("bugprone-", "performance-", "portability-")
        },
        "by_check": dict(by_check.most_common()),
        "items": findings,
    }


def measure(build_dir: Optional[str] = None) -> dict:
    """cppcheck y clang-tidy."""
    print("  cpp: cppcheck...", flush=True)
    check = cppcheck()
    print("  cpp: clang-tidy...", flush=True)
    tidy = clang_tidy(build_dir)
    return {"cppcheck": check, "clang_tidy": tidy}
