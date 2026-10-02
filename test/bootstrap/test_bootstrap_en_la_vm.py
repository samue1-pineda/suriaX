"""bootstrap/en_la_vm — el frontend escrito en suriaX, CORRIENDO en la VM.

El lexer y el parser del bootstrap (``src/frontend/``) son los programas más
grandes del repositorio. Aquí se corren como programas —su volcado de tokens
y su árbol de un fuente de muestra— en la VM y en el intérprete, y se exige
lo mismo de los dos, con cero objetos vivos al terminar. Es el diferencial de
``test/backend/test_vm_diferencial_*.py`` aplicado a la V1: por eso vive en la
categoría ``bootstrap`` (se corre a pedido) y reutiliza su maquinaria.
"""

from __future__ import annotations

import os
import sys

_BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from vm_diferencial_support import _comparar, _del_bootstrap  # noqa: E402


def test_bootstrap_lexer_volcado():
    """El lexer de suriaX, en la VM y en el intérprete: el mismo volcado."""
    _comparar(_del_bootstrap("volcado.srcx"))


def test_bootstrap_parser_sintaxis():
    """El parser de suriaX, en la VM y en el intérprete: el mismo árbol."""
    _comparar(_del_bootstrap("sintaxis.srcx"))
