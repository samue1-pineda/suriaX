"""e2e/stdlib-only — el frontend NO depende de módulos externos.

Contrato del proyecto (``how_to_run.md`` secc. 3): compilar y ver los
diagnósticos EN CONSOLA debe funcionar con una instalación pelada de Python.
Desde que el ``.phir`` se escribe a mano contra el propio ``hir.proto``
(``src/HIR/{schema,wire}.py``), eso vale para el compilador ENTERO: ni
siquiera la fase HIR necesita ``protobuf``, y tampoco un ``protoc`` del
sistema.

Se comprueba de verdad: se lanza el compilador en un subproceso donde
``yaml``/``google.protobuf`` están BLOQUEADOS a nivel de importación.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# lanzador que bloquea los módulos externos y luego ejecuta V0/main.py
_BLOCKER = """
import sys, runpy
BLOCKED = {"yaml", "google", "google.protobuf", "google._upb"}

class Blocker:
    def find_spec(self, name, path=None, target=None):
        if name in BLOCKED or name.split(".")[0] in BLOCKED:
            raise ImportError(f"{name} bloqueado (prueba sin dependencias)")
        return None

sys.meta_path.insert(0, Blocker())
sys.argv = ["main.py"] + sys.argv[1:]
runpy.run_path(MAIN, run_name="__main__")
"""


def _run_without_deps(source: str, *args: str):
    """Compila ``source`` con yaml/protobuf bloqueados. -> (code, out, err)."""
    with tempfile.TemporaryDirectory(prefix="suriax-nodeps-") as tmp:
        src = os.path.join(tmp, "prog.srcx")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(source)
        runner = os.path.join(tmp, "runner.py")
        main_py = os.path.join(_REPO, "V0", "main.py")
        with open(runner, "w", encoding="utf-8") as fh:
            fh.write(f"MAIN = {main_py!r}\n" + _BLOCKER)
        proc = subprocess.run([sys.executable, runner, src, *args],
                              capture_output=True, text=True, cwd=tmp,
                              timeout=120)
        return proc.returncode, proc.stdout, proc.stderr


def test_compila_un_programa_valido_sin_dependencias():
    code, out, err = _run_without_deps(
        "fn suma(int a, int b) -> int { return a + b; };\n"
        "fn main() -> int { return suma(1, 2); };"
    )
    assert code == 0, f"exit={code}\nstdout={out}\nstderr={err}"
    assert "frontend OK" in out, out


def test_diagnosticos_en_consola_sin_dependencias():
    """El caso que importa: los ERRORES se ven en consola sin módulos externos."""
    code, out, err = _run_without_deps("fn f() -> void { var int a = noexiste; };")
    combined = out + err
    assert code == 1, f"exit={code}\n{combined}"
    assert "SEM001" in combined, f"el código de error debe salir en consola:\n{combined}"
    assert "Traceback" not in combined, f"no debe haber traceback:\n{combined}"


def test_directivas_test_funcionan_sin_dependencias():
    for fase, marca in (("lexer", "#test lexer"), ("parser", "#test parser"),
                        ("ast", "#test ast"), ("sem", "#test sem")):
        code, out, err = _run_without_deps(
            f"#test {fase}\nfn f() -> int {{ return 1; }};"
        )
        assert code == 0, f"#test {fase} -> exit={code}\n{out}\n{err}"
        assert marca in out, f"#test {fase} no volcó su salida:\n{out[:200]}"


def test_el_hir_se_emite_SIN_protobuf():
    """``--emit-hir`` funciona con ``google.protobuf`` oculto.

    Antes abortaba pidiendo instalarlo, y como emitir el HIR es parte de
    compilar, la dependencia era de hecho obligatoria para todo — además de
    exigir un ``protoc`` del sistema cuya versión tuviera que ser compatible
    con el runtime de pip. Desde que el ``.phir`` se escribe a mano contra el
    propio ``hir.proto`` (``src/HIR/{schema,wire}.py``), el compilador entero
    no necesita nada instalado.

    Que esos bytes sean protobuf DE VERDAD lo comprueba
    ``test_hir_reproducible.test_el_codec_propio_coincide_con_google_protobuf``
    (y, de punta a punta, el backend C++, que enlaza libprotobuf y los lee).
    """
    code, out, err = _run_without_deps(
        "fn main() -> int { return 0; };", "--emit-hir",
    )
    combined = out + err
    assert code == 0, f"debía compilar sin protobuf, salió {code}:\n{combined}"
    assert "Traceback" not in combined, f"no debe haber traceback:\n{combined}"
    assert "protobuf" not in combined, (
        f"ya no debería pedir protobuf:\n{combined}")


def test_el_frontend_no_importa_modulos_externos():
    """Verificación estática: importar el frontend completo no arrastra
    ``yaml`` ni ``google.protobuf`` al espacio de módulos."""
    codigo = (
        "import sys\n"
        f"sys.path.insert(0, {os.path.join(_REPO, 'V0')!r})\n"
        f"sys.path.insert(0, {_REPO!r})\n"
        "from src.frontend.lexer.lexer import Lexer\n"
        "from src.frontend.parser.parser import Parser\n"
        "from src.frontend.parser.typed_ast import resolve_types\n"
        "from src.frontend.semantic import analyze\n"
        "externos = [m for m in sys.modules if m.split('.')[0] in ('yaml', 'google')]\n"
        "print('EXTERNOS:', externos)\n"
    )
    proc = subprocess.run([sys.executable, "-c", codigo], capture_output=True,
                          text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "EXTERNOS: []" in proc.stdout, (
        f"el frontend importó módulos externos: {proc.stdout}"
    )
