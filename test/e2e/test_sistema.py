"""e2e/sistema — la librería 'sistema' desde la línea de comandos.

El diferencial VM ↔ intérprete (``test_vm_diferencial.py``) ya comprueba que
los dos motores cumplen el mismo contrato. Aquí se prueba lo que solo tiene
el CLI del compilador: que lo que va después de ``--`` es del PROGRAMA y no
de ``suri``, y que el argumento 0 es el fuente que se ejecuta.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_ENV = {**os.environ, "PYTHONUTF8": "1"}

_PROGRAMA = """\
#from io #import stdp
#import sistema.archivos as arch
#import sistema.proceso as proc
fn main() -> int {
    var int i = 0;
    while (i < proc.argumentos()) {
        stdp.println(f"[{i}] {proc.argumento(i)}");
        i = i + 1;
    };
    return proc.argumentos();
}
"""


def _corre(*argumentos: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory(prefix="suriax-sistema-") as tmp:
        shutil.copytree(os.path.join(_REPO, "lib"), os.path.join(tmp, "lib"))
        with open(os.path.join(tmp, "args.srcx"), "w", encoding="utf-8") as fh:
            fh.write(_PROGRAMA)
        return subprocess.run(
            [sys.executable, os.path.join(_REPO, "main.py"), "args.srcx", "--run",
             *argumentos],
            cwd=tmp, capture_output=True, encoding="utf-8", errors="replace",
            env=_ENV, timeout=300)


def test_lo_que_va_despues_de_dos_guiones_es_del_programa():
    proc = _corre("--", "uno", "dos tres", "--time")
    lineas = [l for l in proc.stdout.splitlines() if l.startswith("[")]
    assert lineas == ["[0] args.srcx", "[1] uno", "[2] dos tres", "[3] --time"], (
        proc.stdout, proc.stderr)
    # '--time' era del programa: el compilador no midió nada
    assert "tiempos por fase" not in proc.stdout, proc.stdout
    assert proc.returncode == 4, (proc.returncode, proc.stderr)


def test_sin_dos_guiones_el_programa_solo_ve_su_nombre():
    proc = _corre()
    lineas = [l for l in proc.stdout.splitlines() if l.startswith("[")]
    assert lineas == ["[0] args.srcx"], (proc.stdout, proc.stderr)
    assert proc.returncode == 1, (proc.returncode, proc.stderr)
