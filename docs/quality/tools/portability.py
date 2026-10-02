"""Portabilidad (ISO/IEC 25010, *portability* > *adaptability*): busca en el
código Python lo que funciona en un sistema operativo y no en otro.

Recorre el AST (no el texto: un ``open(`` dentro de un string de suriaX no
es una llamada de Python) y marca:

- ``SIGALRM``, ``signal.alarm``, ``os.fork``, ``os.getuid`` y compañía: solo
  existen en POSIX;
- ``open()`` en modo texto sin ``encoding=``: usa la codificación del sistema
  (UTF-8 en Linux, cp1252 en un Windows en español);
- ``subprocess`` con ``text=True`` / ``universal_newlines=True`` sin
  ``encoding=``: lo mismo con la salida de un proceso;
- ``shell=True``: la sintaxis del shell cambia (``sh`` contra ``cmd.exe``);
- rutas y ejecutables escritos a mano: ``"/tmp"``, ``"python3"``, ``"/dev/null"``;
- ``os.symlink`` fuera de un ``try``: en Windows exige un privilegio.

Uso::

    python docs/quality/tools/portability.py [carpetas...] [--json SALIDA]

Sin carpetas revisa ``test``. Sale con 1 si encuentra algo.
"""

from __future__ import annotations

import ast
import json
import os
import sys
from dataclasses import asdict, dataclass
from typing import Iterator, List

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

#: atributos que solo existen en POSIX
_POSIX_ONLY = {
    ("signal", "SIGALRM"),
    ("signal", "alarm"),
    ("signal", "setitimer"),
    ("signal", "SIGKILL"),
    ("signal", "SIGUSR1"),
    ("signal", "SIGUSR2"),
    ("os", "fork"),
    ("os", "getuid"),
    ("os", "geteuid"),
    ("os", "getpgid"),
    ("os", "setsid"),
    ("os", "killpg"),
    ("os", "WNOHANG"),
}

#: literales que asumen un sistema concreto
_HARDCODED = {
    "/tmp": "usa tempfile",
    "/dev/null": "usa subprocess.DEVNULL u os.devnull",
    "python3": "usa sys.executable",
    "python": "usa sys.executable",
}

_SUBPROCESS_FNS = {"run", "Popen", "check_output", "check_call", "call"}


@dataclass
class Finding:
    """Un hallazgo: dónde está, qué regla rompe y cómo se arregla."""

    file: str
    line: int
    rule: str
    message: str


def _name(node: ast.AST) -> str:
    """``a.b.c`` de una expresión de atributos, o ``""``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _kwarg(call: ast.Call, name: str):
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _is_true(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _open_mode(call: ast.Call) -> str:
    mode = _kwarg(call, "mode")
    if mode is None and len(call.args) >= 2:
        mode = call.args[1]
    if mode is None:
        return "r"
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return mode.value
    return "?"  # un modo calculado: no se puede saber


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.findings: List[Finding] = []
        self._try_depth = 0

    def _add(self, node: ast.AST, rule: str, message: str) -> None:
        self.findings.append(Finding(self.path, getattr(node, "lineno", 0), rule, message))

    def visit_Try(self, node: ast.Try) -> None:
        self._try_depth += 1
        for child in node.body:
            self.visit(child)
        self._try_depth -= 1
        for child in (*node.handlers, *node.orelse, *node.finalbody):
            self.visit(child)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        base = _name(node.value)
        if (base, node.attr) in _POSIX_ONLY:
            self._add(node, "posix-only", f"'{base}.{node.attr}' solo existe en POSIX")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        fn = _name(node.func)
        if fn in ("open", "io.open"):
            mode = _open_mode(node)
            if "b" not in mode and mode != "?" and _kwarg(node, "encoding") is None:
                self._add(
                    node,
                    "open-encoding",
                    "open() en modo texto sin encoding=: depende del sistema",
                )
        if fn.startswith("subprocess.") and fn.split(".")[-1] in _SUBPROCESS_FNS:
            texto = _is_true(_kwarg(node, "text")) or _is_true(_kwarg(node, "universal_newlines"))
            if texto and _kwarg(node, "encoding") is None:
                self._add(
                    node,
                    "subprocess-encoding",
                    "subprocess con text=True sin encoding=: depende del sistema",
                )
            if _is_true(_kwarg(node, "shell")):
                self._add(node, "shell", "shell=True: sh y cmd.exe no hablan igual")
        if fn in ("os.symlink",) and self._try_depth == 0:
            self._add(node, "symlink", "os.symlink fuera de un try: Windows pide un privilegio")
        # rutas o ejecutables escritos a mano como PRIMER argumento de un
        # proceso o de una ruta: ahí es donde rompen
        for arg in node.args[:1]:
            candidatos = arg.elts if isinstance(arg, (ast.List, ast.Tuple)) else [arg]
            for elt in candidatos[:1]:
                if (
                    isinstance(elt, ast.Constant)
                    and elt.value in _HARDCODED
                    and (fn.startswith("subprocess.") or fn.startswith("os.path"))
                ):
                    self._add(elt, "hardcoded", f"{elt.value!r}: {_HARDCODED[elt.value]}")
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and (
            node.value == "/tmp" or node.value.startswith("/tmp/")
        ):
            self._add(node, "hardcoded", f"{node.value!r}: usa tempfile")


def scan_file(path: str) -> List[Finding]:
    """Los hallazgos de un archivo ``.py``."""
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [Finding(path, exc.lineno or 0, "syntax", str(exc))]
    visitor = _Visitor(os.path.relpath(path, ROOT).replace(os.sep, "/"))
    visitor.visit(tree)
    return visitor.findings


def iter_python_files(folders: List[str]) -> Iterator[str]:
    """Los ``.py`` de las carpetas, sin cachés ni ``node_modules``."""
    for folder in folders:
        base = folder if os.path.isabs(folder) else os.path.join(ROOT, folder)
        if os.path.isfile(base):
            yield base
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(
                d
                for d in dirnames
                if d not in ("__pycache__", "node_modules", ".git") and not d.startswith("build")
            )
            for name in sorted(filenames):
                if name.endswith(".py"):
                    yield os.path.join(dirpath, name)


def main(argv: List[str]) -> int:
    json_path = None
    if "--json" in argv:
        i = argv.index("--json")
        json_path = argv[i + 1]
        del argv[i : i + 2]
    folders = argv or ["test"]
    files = list(iter_python_files(folders))
    findings = [f for path in files for f in scan_file(path)]
    for f in findings:
        print(f"{f.file}:{f.line}: [{f.rule}] {f.message}")
    limpios = len(
        {os.path.relpath(p, ROOT).replace(os.sep, "/") for p in files} - {f.file for f in findings}
    )
    print(
        f"portabilidad: {len(findings)} hallazgo(s) en {len(files)} archivo(s); "
        f"{limpios} sin hallazgos"
    )
    if json_path:
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "files": len(files),
                    "clean_files": limpios,
                    "findings": [asdict(f) for f in findings],
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
