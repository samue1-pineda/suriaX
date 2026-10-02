"""El modelo C++ del HIR está AL DÍA con el esquema.

``backend/include/suriax/hir/hir_modelo.hpp`` se genera desde
``V0/src/HIR/proto/hir.proto`` con ``backend/tools/gen_hir_cpp.py`` y se
guarda en el repositorio, para que construir el backend no necesite ni
``protoc`` ni Python. El precio es que puede quedarse atrás: un campo nuevo
en el ``.proto`` que el modelo no conoce se SALTA al leer el ``.phir``
(protobuf ignora lo desconocido), y la VM ejecutaría otro programa sin decir
nada.

Esta prueba no necesita el binario ni un compilador de C++: regenera el
modelo en memoria y lo compara con el guardado, byte a byte.
"""

from __future__ import annotations

import os
import subprocess
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_GENERADOR = os.path.join(_REPO, "backend", "tools", "gen_hir_cpp.py")


def test_el_modelo_cpp_del_hir_coincide_con_el_esquema():
    proc = subprocess.run([sys.executable, _GENERADOR, "--check"],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)
    assert proc.returncode == 0, (
        "el modelo C++ del HIR no corresponde al .proto: "
        "corre 'python backend/tools/gen_hir_cpp.py' y haz commit de los dos "
        f"juntos\n{proc.stderr}")
