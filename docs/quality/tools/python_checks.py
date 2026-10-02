"""Python: PEP 8, PEP 20 y PEP 257 medidos con flake8, black, pylint y
pydocstyle (la configuración está en ``.flake8`` y ``pyproject.toml``).

Cada medición devuelve números, no opiniones: cuántos archivos cumplen,
cuántas violaciones hay y de qué tipo. Una herramienta que no está instalada
se reporta como NO MEDIDA.
"""

from __future__ import annotations

import ast
import json
import re
from collections import Counter
from typing import Dict, List

from common import (
    count_lines,
    PY_SCOPE,
    PY_TESTS,
    iter_files,
    percent,
    python_exe,
    python_module_available,
    rel,
    run,
    tool_version,
)

_FLAKE8_LINE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):(?P<col>\d+): (?P<code>[A-Z]+\d+) (?P<msg>.*)$"
)


def _files(scope: List[str]) -> List[str]:
    return iter_files(scope, (".py",))


# --------------------------------------------------------------------------- #
# flake8: PEP 8 (E/W), pyflakes (F) y complejidad (C901)
# --------------------------------------------------------------------------- #


def flake8(scope: List[str]) -> dict:
    """PEP 8 según pycodestyle, errores lógicos de pyflakes y complejidad."""
    if not python_module_available("flake8"):
        return {"measured": False, "reason": "flake8 no está instalado"}
    files = _files(scope)
    out = run([python_exe(), "-m", "flake8", "--format=default", *[rel(f) for f in files]])
    violations = []
    for line in out.stdout.splitlines():
        m = _FLAKE8_LINE.match(line.strip())
        if m:
            violations.append(
                {
                    "file": m["file"].replace("\\", "/"),
                    "line": int(m["line"]),
                    "code": m["code"],
                    "message": m["msg"],
                }
            )
    pep8 = [v for v in violations if v["code"][0] in "EW"]
    flakes = [v for v in violations if v["code"][0] == "F"]
    complexity = [v for v in violations if v["code"] == "C901"]
    files_rel = {rel(f) for f in files}
    lines = count_lines(files)
    return {
        "measured": True,
        "tool": tool_version([python_exe(), "-m", "flake8", "--version"]),
        "files": len(files),
        "lines": lines,
        "pep8": {
            "violations": len(pep8),
            "per_kloc": round(1000 * len(pep8) / lines, 2) if lines else None,
            "clean_files": len(files_rel - {v["file"] for v in pep8}),
            "clean_files_pct": percent(len(files_rel - {v["file"] for v in pep8}), len(files)),
            "by_code": dict(Counter(v["code"] for v in pep8).most_common()),
        },
        "pyflakes": {
            "violations": len(flakes),
            "by_code": dict(Counter(v["code"] for v in flakes).most_common()),
        },
        "complexity": {
            "over_limit": len(complexity),
            "functions": [f"{v['file']}:{v['line']} {v['message']}" for v in complexity],
        },
        "violations": violations,
    }


# --------------------------------------------------------------------------- #
# black: formato (solo se mide)
# --------------------------------------------------------------------------- #


def black(scope: List[str]) -> dict:
    """Cuántos archivos ya tienen el formato de black (``--check``)."""
    if not python_module_available("black"):
        return {"measured": False, "reason": "black no está instalado"}
    files = _files(scope)
    out = run([python_exe(), "-m", "black", "--check", *[rel(f) for f in files]])
    would = sorted(
        {
            line.split("would reformat ", 1)[1].strip().replace("\\", "/")
            for line in out.stderr.splitlines()
            if "would reformat " in line
        }
    )
    return {
        "measured": True,
        "tool": tool_version([python_exe(), "-m", "black", "--version"]),
        "files": len(files),
        "formatted": len(files) - len(would),
        "formatted_pct": percent(len(files) - len(would), len(files)),
        "would_reformat": would,
    }


# --------------------------------------------------------------------------- #
# pylint: nota global y mensajes por categoría
# --------------------------------------------------------------------------- #

_PYLINT_CATEGORY = {
    "C": "convention",
    "R": "refactor",
    "W": "warning",
    "E": "error",
    "F": "fatal",
    "I": "info",
}


def pylint(scope: List[str]) -> dict:
    """La nota de pylint (sobre 10) y sus mensajes agrupados."""
    if not python_module_available("pylint"):
        return {"measured": False, "reason": "pylint no está instalado"}
    files = _files(scope)
    out = run(
        [
            python_exe(),
            "-m",
            "pylint",
            "--output-format=json2",
            "--score=y",
            *[rel(f) for f in files],
        ],
        timeout=7200,
    )
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        return {"measured": False, "reason": f"pylint no devolvió JSON: {out.stderr[:300]}"}
    messages = data.get("messages", [])
    stats = data.get("statistics", {})
    return {
        "measured": True,
        "tool": tool_version([python_exe(), "-m", "pylint", "--version"]),
        "files": len(files),
        "score": stats.get("score"),
        "by_category": dict(
            Counter(_PYLINT_CATEGORY.get(m["messageId"][0], "?") for m in messages)
        ),
        "by_symbol": dict(Counter(m["symbol"] for m in messages).most_common()),
        "messages": [
            {
                "file": m["path"].replace("\\", "/"),
                "line": m["line"],
                "id": m["messageId"],
                "symbol": m["symbol"],
            }
            for m in messages
        ],
    }


# --------------------------------------------------------------------------- #
# PEP 257: docstrings (AST propio + pydocstyle)
# --------------------------------------------------------------------------- #


def _public_definitions(path: str) -> List[tuple]:
    """``(tipo, nombre, línea, tiene_docstring)`` de lo público de un módulo:
    el módulo, sus clases y funciones, y los métodos de las clases públicas.
    Público = no empieza con ``_`` (los dunder cuentan como públicos, salvo
    ``__init__``, que PEP 257 documenta en la clase)."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        try:
            tree = ast.parse(fh.read())
        except SyntaxError:
            return []
    found = [("module", rel(path), 1, ast.get_docstring(tree) is not None)]

    def public(name: str) -> bool:
        return not name.startswith("_") or (
            name.startswith("__") and name.endswith("__") and name != "__init__"
        )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and public(node.name):
            found.append(("function", node.name, node.lineno, ast.get_docstring(node) is not None))
        elif isinstance(node, ast.ClassDef) and public(node.name):
            found.append(("class", node.name, node.lineno, ast.get_docstring(node) is not None))
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and public(item.name):
                    found.append(
                        (
                            "method",
                            f"{node.name}.{item.name}",
                            item.lineno,
                            ast.get_docstring(item) is not None,
                        )
                    )
    return found


def docstrings(scope: List[str]) -> dict:
    """PEP 257: qué parte de lo público está documentado (AST) y cuántos
    docstrings rompen sus reglas de forma (pydocstyle, códigos D2xx-D4xx)."""
    files = _files(scope)
    definitions = [d for f in files for d in _public_definitions(f)]
    documented = sum(1 for d in definitions if d[3])
    result = {
        "measured": True,
        "files": len(files),
        "public_definitions": len(definitions),
        "documented": documented,
        "documented_pct": percent(documented, len(definitions)),
        "by_kind": {
            kind: {
                "total": sum(1 for d in definitions if d[0] == kind),
                "documented": sum(1 for d in definitions if d[0] == kind and d[3]),
            }
            for kind in ("module", "class", "function", "method")
        },
    }
    if not python_module_available("pydocstyle"):
        result["form"] = {"measured": False, "reason": "pydocstyle no está instalado"}
        return result
    out = run([python_exe(), "-m", "pydocstyle", *[rel(f) for f in files]], timeout=3600)
    codes = re.findall(r"^\s+(D\d{3}):", out.stdout, flags=re.MULTILINE)
    form = [c for c in codes if not c.startswith("D1")]  # D1xx = falta docstring
    result["form"] = {
        "measured": True,
        "tool": "pydocstyle " + tool_version([python_exe(), "-m", "pydocstyle", "--version"]),
        "violations": len(form),
        "per_docstring": round(len(form) / documented, 2) if documented else None,
        "by_code": dict(Counter(form).most_common()),
    }
    return result


# --------------------------------------------------------------------------- #
# PEP 20: los aforismos que se pueden medir
# --------------------------------------------------------------------------- #


def _silent_handlers(files: List[str]) -> Dict[str, int]:
    """``except`` cuyo cuerpo es solo ``pass`` (o ``...``): el error se traga."""
    total = silent = 0
    where: List[str] = []
    for path in files:
        with open(path, encoding="utf-8", errors="replace") as fh:
            try:
                tree = ast.parse(fh.read())
            except SyntaxError:
                continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                total += 1
                body = node.body
                if all(
                    isinstance(s, ast.Pass)
                    or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
                    for s in body
                ):
                    silent += 1
                    where.append(f"{rel(path)}:{node.lineno}")
    return {"handlers": total, "silent": silent, "where": where}


def zen(scope: List[str], flake: dict, lint: dict) -> dict:
    """PEP 20 no es verificable entero; estos son los aforismos con una
    medida objetiva, cada uno con la suya (ver normas/python.md)."""
    files = _files(scope)
    handlers = _silent_handlers(files)
    functions = sum(1 for f in files for d in _all_functions(f))
    symbols = lint.get("by_symbol", {}) if lint.get("measured") else {}
    flakes = flake.get("pyflakes", {}).get("by_code", {}) if flake.get("measured") else {}
    return {
        "simple_is_better_than_complex": {
            "functions": functions,
            "over_complexity_limit": flake.get("complexity", {}).get("over_limit"),
            "within_pct": percent(
                functions - (flake.get("complexity", {}).get("over_limit") or 0), functions
            ),
        },
        "flat_is_better_than_nested": {
            "too_many_nested_blocks": symbols.get("too-many-nested-blocks"),
        },
        "errors_should_never_pass_silently": {
            "except_handlers": handlers["handlers"],
            "silent_handlers": handlers["silent"],
            "not_silent_pct": percent(
                handlers["handlers"] - handlers["silent"], handlers["handlers"]
            ),
            "bare_except": symbols.get("bare-except"),
            "broad_exception_caught": symbols.get("broad-exception-caught"),
            "where_silent": handlers["where"],
        },
        "explicit_is_better_than_implicit": {
            "wildcard_imports": (
                (flakes.get("F403", 0) + flakes.get("F405", 0)) if flakes else None
            ),
        },
        "there_should_be_one_obvious_way": {
            "duplicate_code_blocks": symbols.get("duplicate-code"),
        },
    }


def _all_functions(path: str):
    with open(path, encoding="utf-8", errors="replace") as fh:
        try:
            tree = ast.parse(fh.read())
        except SyntaxError:
            return []
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def measure(include_tests: bool = True) -> dict:
    """Todas las mediciones de Python, para el compilador y (aparte) la suite."""
    result = {}
    for name, scope in (("compiler", PY_SCOPE), ("tests", PY_TESTS)):
        if name == "tests" and not include_tests:
            continue
        print(f"  python/{name}: flake8...", flush=True)
        flake = flake8(scope)
        print(f"  python/{name}: black...", flush=True)
        fmt = black(scope)
        print(f"  python/{name}: pylint...", flush=True)
        lint = pylint(scope)
        print(f"  python/{name}: docstrings...", flush=True)
        docs = docstrings(scope)
        result[name] = {
            "scope": scope,
            "flake8": flake,
            "black": fmt,
            "pylint": lint,
            "pep257": docs,
            "pep20": zen(scope, flake, lint),
        }
    return result
