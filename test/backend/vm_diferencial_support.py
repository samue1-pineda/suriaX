"""Lo compartido por los ``test_vm_diferencial_*.py`` (antes un solo archivo,
``test_vm_diferencial.py``, partido por tema). Aqui van los imports, las constantes y los
helpers; cada modulo de pruebas importa lo que usa.

backend/vm_diferencial — la VM de C++ contra el intérprete, programa por programa.

El intérprete es el ORÁCULO (invariante A-4): un programa tiene que dar la
misma salida, el mismo código de salida y los mismos códigos de error
(``RTxxx``/``EXCxxx``) en los dos motores. Los dos ejecutan el MISMO
``.phir``, así que una diferencia es de un motor y no del compilador.

El corpus son los programas que el repositorio ya tiene y cuya salida ya
está fijada por otras pruebas —la serie de excepciones, los programas de
fuego, el proyecto de varios archivos y los dos programas del bootstrap
(el lexer y el parser escritos en suriaX)—, más programas mínimos para cada
construcción que la VM aprendió a bajar y que el corpus no toca.

Una prueba por programa: cuando algo diverge, el nombre de la prueba ya dice
cuál.

Se OMITE (``helpers.omitir``) si ``suriax-hir`` no está construido:

    cmake -S . -B build && cmake --build build --target suriax-hir
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import omitir  # noqa: E402

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_COMPILER = os.path.join(_REPO, "main.py")
_INTERP = os.path.join(_REPO, "runtime", "interpreter", "main.py")
_FRONTEND = os.path.join(_REPO, "src", "frontend")
_ENV = {**os.environ, "PYTHONUTF8": "1"}
_CODIGO = re.compile(r"\b(RT\d{3}|EXC\d{3}|ICE\d{3})\b")


def _binario() -> str | None:
    from helpers import hir_binary
    return hir_binary()


def _salida(stdout: str) -> list:
    """Lo que imprimió el PROGRAMA, sin lo que dicen el compilador o la VM."""
    return [l for l in stdout.splitlines()
            if not l.startswith(("frontend OK", "HIR ", "[exit]", "[vm] main() -> "))
            and not (l.lstrip().startswith("unidad '") and " -> " in l)]


def _comparar(preparar, argumentos=()) -> None:
    """Arma el proyecto con ``preparar(dir) -> fuente``, lo compila una vez
    y lo corre en los dos motores, con ``argumentos`` para el programa."""
    vm = _binario()
    if vm is None:
        omitir("suriax-hir no está construido "
               "(cmake -S . -B build && cmake --build build --target suriax-hir)")
    with tempfile.TemporaryDirectory(prefix="suriax-vmdif-") as tmp:
        fuente = preparar(tmp)
        # la raiz del proyecto es la carpeta del fuente: ahi van 'lib' y el
        # yaml, y 'native' hace que las unidades de librería se emitan junto
        # al .phir, que es donde las buscan los dos motores
        raiz = os.path.dirname(fuente)
        if not os.path.isdir(os.path.join(raiz, "lib")):
            shutil.copytree(os.path.join(_REPO, "lib"), os.path.join(raiz, "lib"))
        with open(os.path.join(raiz, ".suriaX_config.yaml"), "w",
                  encoding="utf-8") as fh:
            fh.write("version: 1\ntarget: native\n")
        phir = os.path.join(raiz, "prog.phir")
        emit = subprocess.run([sys.executable, _COMPILER, fuente, "--emit-hir", phir],
                              cwd=raiz, capture_output=True, encoding="utf-8",
                              errors="replace", env=_ENV, timeout=300)
        assert os.path.isfile(phir), (emit.stdout[-800:], emit.stderr[-800:])
        interp = subprocess.run([sys.executable, _INTERP, phir, "--exec", "--", *argumentos], cwd=raiz,
                                capture_output=True, encoding="utf-8",
                                errors="replace", env=_ENV, timeout=600)
        maquina = subprocess.run([vm, phir, "--run", "--memoria", "--", *argumentos],
                                 cwd=raiz, capture_output=True, encoding="utf-8",
                                 errors="replace", timeout=600)
    # la VM sale con 1 cuando el MIR no cubre algo: eso nunca es "igual"
    assert "no cubre" not in maquina.stderr + maquina.stdout, (
        maquina.stderr[-1500:] or maquina.stdout[-1500:])
    assert _salida(maquina.stdout) == _salida(interp.stdout), (
        "salidas distintas", _salida(interp.stdout)[-6:],
        _salida(maquina.stdout)[-6:], maquina.stderr[-400:])
    assert maquina.returncode == interp.returncode, (
        interp.returncode, maquina.returncode, interp.stderr[-300:],
        maquina.stderr[-300:])
    assert sorted(set(_CODIGO.findall(maquina.stderr + maquina.stdout))) == \
        sorted(set(_CODIGO.findall(interp.stderr))), (
        interp.stderr[-300:], maquina.stderr[-300:])
    _sin_fugas(maquina.stdout, maquina.stderr)


def _sin_fugas(stdout: str, stderr: str) -> None:
    """Un programa que termina NORMALMENTE (vuelve de 'main') no deja objetos
    vivos: cada uno muere con su dueño. Uno que aborta (una excepción que
    nadie atrapa, un RT, 'salir') no cierra sus ámbitos, como un proceso que
    muere, y no se mide."""
    if "[vm] main() -> " not in stdout:
        return
    vivos = re.search(r"vivos al terminar (\d+)", stderr)
    assert vivos is not None, stderr[-400:]
    detalle = [l for l in stderr.splitlines() if "vivo:" in l]
    assert vivos.group(1) == "0", ("la VM dejó objetos vivos al terminar", detalle)
    cadenas = re.search(r"cadenas creadas \d+, recogidas \d+, vivas al terminar (\d+)", stderr)
    assert cadenas is not None and cadenas.group(1) == "0", (
        "la VM dejó cadenas vivas al terminar", stderr[-300:])

# los programas del bootstrap (su lexer y su parser corriendo en la VM) son
# de la categoria 'bootstrap': ver test/bootstrap/test_bootstrap_en_la_vm.py


# --------------------------------------------------------------------------- #
# construcciones sueltas: lo que la VM aprendió a bajar y el corpus no toca
# --------------------------------------------------------------------------- #

def _en_linea(fuente: str):
    def preparar(tmp: str) -> str:
        ruta = os.path.join(tmp, "prog.srcx")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(fuente)
        return ruta
    return preparar


def _hay_cxx() -> bool:
    return bool(os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++"))


def _del_bootstrap(archivo: str):
    """Prepara un programa del bootstrap (src/frontend) con su librería: lo
    usa la categoría 'bootstrap' (test_bootstrap_en_la_vm.py)."""
    def preparar(tmp: str) -> str:
        shutil.copytree(os.path.join(_REPO, "lib"), os.path.join(tmp, "lib"))
        shutil.copytree(_FRONTEND, os.path.join(tmp, "lib", "frontend"))
        shutil.copy(os.path.join(_FRONTEND, archivo), tmp)
        return os.path.join(tmp, archivo)
    return preparar
