"""e2e/cliente_vscode — el cliente de la extensión, sin VS Code.

``tooling/vscode/extension.js`` corre en node con un módulo ``vscode`` falso
(``cliente_vscode/arnes.js``) y habla con el servidor de lenguaje DE VERDAD,
lanzado como lo lanza en el editor (``lanzar.py --lsp`` con el Python y la
raíz de los ajustes). Prueba la mitad que el resto de la suite no ve: que el
cliente traduce el protocolo a la API del editor —diagnósticos, hover,
definición, símbolos, completar—, que manda el texto sin guardar, que
registra cómo lanzar el depurador y que al desactivarse apaga al servidor.

No prueba la API de VS Code (el ``vscode`` es falso) ni una ventana real.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_TEST = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TEST not in sys.path:
    sys.path.insert(0, _TEST)
from helpers import omitir  # noqa: E402

_EXTENSION = os.path.join(_REPO, "tooling", "vscode")
_ARNES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cliente_vscode", "arnes.js")

_PROGRAMA = """\
#from io #import stdp

// el doble de n
fn doble(int n) -> int {
    return n * 2;
}

fn main() -> int {
    var int a = doble(3);
    stdp.println(f"{a}");
    return 0;
}
"""


def _posicion(texto: str, trozo: str, desplazamiento: int = 0) -> dict:
    indice = texto.index(trozo) + desplazamiento
    return {"line": texto.count("\n", 0, indice),
            "character": indice - (texto.rfind("\n", 0, indice) + 1)}


def test_el_cliente_traduce_el_servidor_a_la_api_del_editor():
    node = shutil.which("node")
    if node is None:
        omitir("node no está en el PATH: el cliente de la extensión es JavaScript")
    with tempfile.TemporaryDirectory(prefix="suriax-cliente-") as tmp:
        entrada = os.path.join(tmp, "entrada.json")
        with open(entrada, "w", encoding="utf-8") as fh:
            json.dump({
                "carpeta": tmp,
                "roto": _PROGRAMA.replace("return 0;", "return nada;"),
                "programa": _PROGRAMA,
                "hover": _posicion(_PROGRAMA, "doble(3)", 1),
                "definicion": _posicion(_PROGRAMA, "println", 2),
                "completar": _posicion(_PROGRAMA, "println"),
            }, fh)
        hecho = subprocess.run([node, _ARNES, _EXTENSION, sys.executable, _REPO, entrada],
                               cwd=tmp, capture_output=True, timeout=180)
    salida, errores = hecho.stdout.decode("utf-8"), hecho.stderr.decode("utf-8")
    assert hecho.returncode == 0, (hecho.returncode, errores[-1500:])
    visto = json.loads(salida)

    # el texto sin guardar, con su error, llegó y volvió como Diagnostic
    error, = visto["diagnosticosRotos"]
    assert error["code"] == "SEM001" and error["severity"] == 0, error   # Error de VS Code
    roto = _PROGRAMA.replace("return 0;", "return nada;")
    assert error["range"]["start"] == _posicion(roto, "nada"), error

    assert "fn doble(int n) -> int" in visto["hover"]["valor"], visto["hover"]
    assert visto["definicion"]["uri"].endswith("/lib/io/stdp.libsrx"), visto["definicion"]
    # los tipos del LSP empiezan en 1 y los de VS Code en 0: Function es 11
    assert [(s["name"], s["kind"]) for s in visto["simbolos"]] == [("doble", 11), ("main", 11)]
    assert visto["simbolos"][1]["children"] == ["a"]
    assert {"println", "print"} <= set(visto["completar"]), visto["completar"]

    # el depurador, con el mismo Python y el mismo compilador
    depurador = visto["depurador"]
    assert depurador["command"] == sys.executable
    assert depurador["args"] == [os.path.join(_EXTENSION, "lanzar.py"), "--dap"]
    assert depurador["options"]["env"] == {"SURIAX_ROOT": _REPO}

    assert visto["comandos"] == ["suriax.reiniciarServidor"]
    # ni una caída ni un aviso de versiones: la extensión es la de este compilador
    assert visto["avisos"] == [], visto["avisos"]
