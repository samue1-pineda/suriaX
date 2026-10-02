"""e2e/run_motor — '--run' elige el motor: la VM compilada o el intérprete.

    suri prog.srcx                        # el motor del 'target' del yaml
    suri prog.srcx --run compiler         # la VM (suriax-hir)
    suri prog.srcx --run interpreter      # el intérprete de Python

Sin yaml, el 'target' por defecto es 'native': la VM. Si la VM no está
construida (o su MIR no cubre el programa) se interpreta, con un AVISO: la
semántica es la misma —la comprueba el diferencial—, pero ejecutar en otro
motor del que se pidió nunca pasa en silencio.

Las pruebas que necesitan la VM se omiten si no está construida.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import omitir  # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MAIN = os.path.join(_REPO, "main.py")

_PROGRAMA = """\
#from io #import stdp
#import sistema.proceso as proc
fn main() -> int {
    stdp.println(f"hola {proc.argumentos()} {proc.argumento(1)}");
    return 3;
}
"""


def _vm() -> str | None:
    from helpers import hir_binary
    return hir_binary()


def _correr(*banderas: str, vm: str | None) -> subprocess.CompletedProcess:
    entorno = {**os.environ, "PYTHONUTF8": "1",
               # un binario que no existe = la VM no esta construida
               "SURIAX_HIR_BIN": vm or os.path.join(_REPO, "no", "existe")}
    with tempfile.TemporaryDirectory(prefix="suriax-motor-") as tmp:
        fuente = os.path.join(tmp, "prog.srcx")
        with open(fuente, "w", encoding="utf-8") as fh:
            fh.write(_PROGRAMA)
        return subprocess.run([sys.executable, _MAIN, "prog.srcx", *banderas, "--", "x"],
                              cwd=tmp, capture_output=True, encoding="utf-8",
                              errors="replace", env=entorno, timeout=300)


def test_interpreter_forzado_no_necesita_la_vm():
    r = _correr("--run", "interpreter", vm=None)
    assert "hola 2 x" in r.stdout, r.stdout + r.stderr
    assert r.returncode == 3
    assert "no esta construida" not in r.stderr


def test_sin_la_vm_se_interpreta_con_un_aviso():
    r = _correr("--run", "compiler", vm=None)
    assert "hola 2 x" in r.stdout, r.stdout + r.stderr
    assert r.returncode == 3
    assert "la VM (suriax-hir) no esta construida" in r.stderr, r.stderr


def test_por_defecto_compila_en_la_vm():
    """Sin yaml el target es 'native': la VM, con el mismo resultado y el
    mismo codigo de salida que el interprete, y sin la linea '[vm] ...'."""
    vm = _vm()
    if vm is None:
        omitir("suriax-hir no está construido")
    r = _correr(vm=vm)
    assert "hola 2 x" in r.stdout, r.stdout + r.stderr
    assert "[vm]" not in r.stdout
    assert "no esta construida" not in r.stderr and "no cubre" not in r.stderr
    assert r.returncode == 3


def test_run_compiler_con_la_vm():
    vm = _vm()
    if vm is None:
        omitir("suriax-hir no está construido")
    r = _correr("--run", "compiler", vm=vm)
    assert "hola 2 x" in r.stdout and r.returncode == 3, r.stdout + r.stderr


def test_un_motor_que_no_existe_es_un_error_de_uso():
    r = _correr("--run=rapido", vm=None)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "compiler" in r.stderr and "interpreter" in r.stderr
