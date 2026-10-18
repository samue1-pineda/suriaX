"""unit/dependency_report — ``--check`` y las dependencias opcionales.

``protobuf`` (solo la comprobación cruzada del codec) y ``pybind11`` (solo
para construir los módulos nativos) son OPCIONALES: antes salían como
``[FALTA]`` y ``--check`` terminaba en 1 en una máquina que compilaba y
ejecutaba bien. Y ``driver/artifacts.py`` culpaba a protobuf de cualquier
fallo al cargar el emisor del HIR, aunque el emisor ya no lo usa.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import helpers  # noqa: E402,F401  (pone V0/ y la raíz en sys.path)


def test_protobuf_and_pybind11_are_optional_and_pyyaml_is_not():
    from config.dependencies import check_dependencies
    report = check_dependencies()
    assert report["protobuf"]["optional"] and report["protobuf"]["use"]
    assert report["pybind11"]["optional"] and report["pybind11"]["use"]
    assert not report["pyyaml"]["optional"]


def _report_with(missing: set) -> tuple:
    """``_print_report`` con las dependencias de ``missing`` ausentes."""
    from config import compilerconfig, dependencies
    real = dependencies._check_python_module

    def fake(module):
        names = {"google.protobuf": "protobuf", "pybind11": "pybind11", "yaml": "pyyaml"}
        return None if names.get(module) in missing else "1.0"

    dependencies._check_python_module = fake
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            code = compilerconfig._print_report()
    finally:
        dependencies._check_python_module = real
    return code, out.getvalue()


def test_missing_optional_dependencies_do_not_fail_the_check():
    code, out = _report_with({"protobuf", "pybind11"})
    assert "[OPCIONAL] protobuf" in out and "[OPCIONAL] pybind11" in out, out
    assert "FALTA" not in out, out
    assert code == 0, out


def test_a_missing_required_dependency_still_fails_the_check():
    code, out = _report_with({"pyyaml"})
    assert "[FALTA] pyyaml" in out, out
    assert code == 1, out


def test_the_hir_phase_reports_the_real_cause_of_a_broken_emitter():
    """Si el emisor no carga, el motivo es la excepción real, no protobuf."""
    from driver import artifacts
    names = ("src.HIR.emmit_IR",)
    saved = {n: sys.modules.get(n) for n in names}
    for n in names:
        sys.modules[n] = None        # importar un None de sys.modules: ModuleNotFoundError
    try:
        payload = artifacts.collect("fn main() -> int { return 0; }\n")
    finally:
        for n, mod in saved.items():
            if mod is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = mod
    reason = payload["phases"]["hir"]["reason"]
    assert "protobuf" not in reason, reason
    assert "ModuleNotFoundError" in reason and "emisor del HIR" in reason, reason
