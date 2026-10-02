"""La suite de pruebas como fuente de medidas (ISO/IEC 25010 e ISO/IEC/IEEE
29119): cuántas pasan, cuántas no se ejecutaron y por qué, y qué parte del
compilador ejercitan (cobertura con coverage.py).

La suite se corre con SU runner (``test/main.py``), igual que siempre: esto
solo guarda el resumen. No se mezcla con ella ni la cambia.
"""

from __future__ import annotations

import glob
import json
import os
from collections import Counter
from typing import List, Optional

from common import REPORTS, ROOT, percent, python_exe, python_module_available, run, tool_version


def run_suite(categories: Optional[List[str]] = None) -> dict:
    """``test/main.py`` (``--todo`` si no se piden categorías) con resumen JSON."""
    summary = os.path.join(REPORTS, "suite.json")
    os.makedirs(REPORTS, exist_ok=True)
    selected = categories or ["--todo"]
    out = run(
        [python_exe(), os.path.join("test", "main.py"), *selected, "--json", summary],
        timeout=14400,
    )
    if not os.path.isfile(summary):
        return {"measured": False, "reason": f"la suite no produjo resumen: {out.stderr[-500:]}"}
    with open(summary, encoding="utf-8") as fh:
        data = json.load(fh)
    executed = data["passed"] + data["failed"]
    reasons = Counter(s.get("reason", "?") for s in data.get("skips", []))
    return {
        "measured": True,
        "categories": data["categories"],
        "modules": data["modules"],
        "total": data["total"],
        "passed": data["passed"],
        "failed": data["failed"],
        "skipped": data["skipped"],
        "pass_pct_of_executed": percent(data["passed"], executed),
        "executed_pct": percent(executed, data["total"]),
        "failures": [
            f"{f.get('category')}/{f.get('module')}::{f.get('test')}: {f.get('error')}"
            for f in data.get("failures", [])
        ],
        "skip_reasons": dict(reasons.most_common()),
        "skipped_by_category": dict(
            Counter(s.get("category", "?") for s in data.get("skips", []))
        ),
        "per_category": _per_category(),
    }


def _per_category() -> dict:
    """Módulos y pruebas por categoría (cuenta estática de ``def test_``)."""
    result = {}
    base = os.path.join(ROOT, "test")
    for category in sorted(os.listdir(base)):
        folder = os.path.join(base, category)
        if not os.path.isdir(folder) or category.startswith(("_", ".")):
            continue
        modules = glob.glob(os.path.join(folder, "**", "test_*.py"), recursive=True)
        if not modules:
            continue
        tests = 0
        for path in modules:
            with open(path, encoding="utf-8", errors="replace") as fh:
                tests += sum(1 for line in fh if line.startswith("def test_"))
        result[category] = {"modules": len(modules), "tests": tests}
    return result


def coverage(categories: Optional[List[str]] = None) -> dict:
    """Cobertura de líneas y ramas del compilador (``[tool.coverage]`` en
    ``pyproject.toml``) con la suite. Los subprocesos se miden también."""
    if not python_module_available("coverage"):
        return {"measured": False, "reason": "coverage no está instalado"}
    data_dir = os.path.join(REPORTS, "coverage")
    os.makedirs(data_dir, exist_ok=True)
    for old in glob.glob(os.path.join(data_dir, ".coverage*")):
        os.remove(old)
    env = dict(os.environ, COVERAGE_FILE=os.path.join(data_dir, ".coverage"), PYTHONUTF8="1")
    selected = categories or ["--todo"]
    run(
        [
            python_exe(),
            "-m",
            "coverage",
            "run",
            "--rcfile=pyproject.toml",
            os.path.join("test", "main.py"),
            *selected,
        ],
        env=env,
        timeout=28800,
    )
    run([python_exe(), "-m", "coverage", "combine", "--rcfile=pyproject.toml", data_dir], env=env)
    report = os.path.join(REPORTS, "coverage.json")
    out = run(
        [python_exe(), "-m", "coverage", "json", "--rcfile=pyproject.toml", "-o", report], env=env
    )
    if not os.path.isfile(report):
        return {"measured": False, "reason": f"coverage no generó el informe: {out.stderr[-500:]}"}
    with open(report, encoding="utf-8") as fh:
        data = json.load(fh)
    totals = data["totals"]
    by_package: dict = {}
    for path, info in data["files"].items():
        package = path.replace("\\", "/").split("/")[0]
        entry = by_package.setdefault(package, {"statements": 0, "covered": 0})
        entry["statements"] += info["summary"]["num_statements"]
        entry["covered"] += info["summary"]["covered_lines"]
    for entry in by_package.values():
        entry["pct"] = percent(entry["covered"], entry["statements"])
    return {
        "measured": True,
        "tool": tool_version([python_exe(), "-m", "coverage", "--version"]),
        "line_pct": round(totals["percent_covered"], 1),
        "statements": totals["num_statements"],
        "covered_lines": totals["covered_lines"],
        "branches": totals.get("num_branches"),
        "covered_branches": totals.get("covered_branches"),
        "branch_pct": percent(totals.get("covered_branches", 0), totals.get("num_branches", 0)),
        "by_package": by_package,
    }
