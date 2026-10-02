"""Lo compartido por los ``test_diagnostics_*.py`` (antes un solo archivo,
``test_diagnostics.py``, partido por tema). Aqui van los imports, las constantes y los
helpers; cada modulo de pruebas importa lo que usa.

negative_tests — cada diagnóstico se dispara EN SU CASO y no en otros.

Se comprueba el CÓDIGO (``SEM001``, ``AST006``...), nunca el texto del
mensaje: los mensajes se reescriben, los códigos son el contrato estable.

El otro lado del contrato importa igual: un programa VÁLIDO no debe producir
diagnósticos (cero falsos positivos, ver ``semantic/ARQUITECTURA.md`` 4.2).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

