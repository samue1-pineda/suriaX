"""Lo compartido por los ``test_libraries_*.py`` (antes un solo archivo,
``test_libraries.py``, partido por tema). Aqui van los imports, las constantes y los
helpers; cada modulo de pruebas importa lo que usa.

e2e/libraries — importar y USAR librerías y paquetes de punta a punta.

Cubre la capa que va del linker de librerías (``V0/src/linker_p/``) al
*module linker* del intérprete: resolver el ``#import``, emitir un ``.phir``
por unidad, ligarlas en una imagen y que ``modulo.funcion(...)`` ejecute el
cuerpo correcto.

Cada test escribe su propio árbol de proyecto en un temporal
(``helpers.run_project``), así la suite NO depende del estado real de
``lib/``: lo que se prueba es el mecanismo, no el contenido de la stdlib.

Nombres de unidad: una unidad se identifica por su nombre CALIFICADO
(``IO.stdp``), no por el alias suelto del submódulo — es lo que permite que
dos paquetes publiquen un submódulo homónimo sin pisarse.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


W = "fn __write__(str s) -> void;\n"

#: un paquete 'text' con DOS submódulos: el caso que exige nombres calificados.
PKG = {
    "lib/text/main.libsrx": "#export package as text\n",
    "lib/text/upper.libsrx": W + """
fn shout(str s) -> void { __write__(s); __write__("!\\n"); }
fn twice(int n) -> int { return n * 2; }
#export as upper
""",
    "lib/text/lower.libsrx": W + """
fn whisper(str s) -> void { __write__(s); __write__("...\\n"); }
#export as lower
""",
}


def _main(body: str, extra: str = "") -> dict:
    return {**PKG, "main.srcx": extra + "\nfn main() -> int {\n" + body +
            "\n    return 0;\n};\n"}
