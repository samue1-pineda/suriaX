"""backend/vm_diferencial: el corpus del repositorio, una prueba por programa (la VM contra el interprete).

Parte de ``test_vm_diferencial.py`` (partido por tema); lo compartido esta en
``vm_diferencial_support.py``.
"""

import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vm_diferencial_support import (  # noqa: E402
    _REPO,
    _comparar,
)

# --------------------------------------------------------------------------- #
# el corpus del repositorio: una prueba por programa
# --------------------------------------------------------------------------- #

def _de_carpeta(carpeta: str, archivo: str):
    def preparar(tmp: str) -> str:
        destino = os.path.join(tmp, "p")
        shutil.copytree(carpeta, destino)
        return os.path.join(destino, archivo)
    return preparar


def _registrar(nombre: str, preparar) -> None:
    def prueba():
        _comparar(preparar)
    prueba.__name__ = nombre
    prueba.__doc__ = "La VM y el intérprete dan lo mismo."
    globals()[nombre] = prueba


def _identificador(texto: str) -> str:
    return re.sub(r"\W", "_", os.path.splitext(texto)[0]).lower()


for _carpeta, _prefijo in ((os.path.join(_REPO, "test", "e2e", "excepciones"), "excepciones"),
                           (os.path.join(_REPO, "test", "e2e", "fuego"), "fuego"),
                           (os.path.join(_REPO, "test", "e2e", "fuego", "proyecto"),
                            "proyecto")):
    for _archivo in sorted(os.listdir(_carpeta)):
        if _archivo.endswith(".srcx"):
            _registrar(f"test_{_prefijo}_{_identificador(_archivo)}",
                       _de_carpeta(_carpeta, _archivo))
