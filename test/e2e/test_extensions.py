"""HTIMS de punta a punta: la capa previa al léxico, vista desde la CLI.

Comprueba lo que un usuario percibe: que un proyecto con ``extends.srcx``
compila y puede consultarse con ``--emit-extensions``, que uno con el
manifiesto roto se detiene ANTES de tokenizar, y —lo más importante— que un
proyecto SIN extensiones sigue compilando exactamente igual que antes de que
esta capa existiera.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from helpers import run_project  # noqa: E402

_CONFIG = "version: 1\ntarget: interp\n"

_MAIN = "fn main() -> int { return 0; }\n"

_MANIFEST = ("# manifiesto del proyecto\n"
             "project:   MiJuego\n"
             "logic_dir: extensions/logic\n"
             "calls_dir: extensions/calls\n")

_PHYSICS = ('from htims import hook\n'
            'PROJECT = "MiJuego"\n'
            '@hook("__gravity__", owner="Body",\n'
            '      params=["Body ptr mutable", "float"], returns="void",\n'
            '      logic="gravity_cpp")\n'
            'def gravity(body, dt): pass\n')


def _project(**extra) -> dict:
    files = {
        ".suriaX_config.yaml": _CONFIG,
        "juego.srcx": _MAIN,
        "extends.srcx": _MANIFEST,
        "extensions/logic/.keep": "",
        "extensions/calls/physics.py": _PHYSICS,
    }
    files.update(extra)
    return files


# --------------------------------------------------------------------------- #
# no romper lo que ya funcionaba
# --------------------------------------------------------------------------- #

def test_un_proyecto_sin_extensiones_compila_igual():
    code, out, err = run_project(
        {".suriaX_config.yaml": _CONFIG, "main.srcx": _MAIN}, args=["--run"])
    assert code == 0, err
    assert "frontend OK" in out


def test_un_proyecto_con_extensiones_compila_y_ejecuta():
    """Las declaraciones se leen, pero el vocabulario fijo no cambia todavía:
    un .srcx que no las usa compila y corre como siempre."""
    code, out, err = run_project(_project(), main="juego.srcx", args=["--run"])
    assert code == 0, err
    assert "frontend OK" in out


# --------------------------------------------------------------------------- #
# la consulta
# --------------------------------------------------------------------------- #

def test_emit_extensions_describe_lo_declarado():
    code, out, err = run_project(_project(), main="juego.srcx",
                                 args=["--emit-extensions"])
    assert code == 0, err
    payload = json.loads(out)
    assert payload["project"] == "MiJuego"
    hooks = payload["extensions"]["hooks"]
    assert [h["name"] for h in hooks] == ["__gravity__"]
    assert hooks[0]["owner"] == "Body"
    assert hooks[0]["params"] == ["Body ptr mutable", "float"]
    assert hooks[0]["logic"] == "gravity_cpp"
    # y las líneas que el usuario puede copiar a su yaml
    assert payload["config_entries"] == [
        {"path": os.path.join("extensions", "calls", "physics.py"),
         "logic": ["gravity_cpp"]}]


def test_emit_extensions_sin_extensiones_no_es_un_error():
    code, out, _ = run_project(
        {".suriaX_config.yaml": _CONFIG, "main.srcx": _MAIN},
        args=["--emit-extensions"])
    assert code == 0
    payload = json.loads(out)
    assert payload["extensions"] is None
    assert payload["diagnostics"] == []


# --------------------------------------------------------------------------- #
# el manifiesto roto detiene la compilación
# --------------------------------------------------------------------------- #

def test_un_manifiesto_roto_aborta_antes_de_compilar():
    files = _project(**{"extends.srcx": _MANIFEST.replace(
        "calls_dir: extensions/calls", "calls_dir: extensions/fantasma")})
    code, out, err = run_project(files, main="juego.srcx", args=["--run"])
    assert code == 4, (code, out, err)
    assert "EXT003" in err
    # se detuvo ANTES del léxico: no llegó a reportar el frontend.
    assert "frontend OK" not in out


def test_el_error_del_manifiesto_llega_al_canal_del_editor():
    files = _project(**{"extends.srcx": "linea suelta\n"})
    code, out, err = run_project(files, main="juego.srcx",
                                 args=["--emit-diagnostics"])
    assert code == 0, err  # el canal NUNCA falla: los errores van en el JSON
    payload = json.loads(out)
    codes = [d["code"] for d in payload["diagnostics"]]
    assert "EXT002" in codes
    entry = next(d for d in payload["diagnostics"] if d["code"] == "EXT002")
    assert entry["file"].endswith("extends.srcx")   # el manifiesto, no el .srcx
    assert entry["severity"] == "critical"
    assert entry["end_column"] == entry["column"] + 1


def test_una_extension_con_python_roto_aborta_con_ext011():
    files = _project(**{"extensions/calls/physics.py": "def roto(:\n"})
    code, _, err = run_project(files, main="juego.srcx")
    assert code == 4
    assert "EXT011" in err


# --------------------------------------------------------------------------- #
# la garantía, verificada en la CLI real
# --------------------------------------------------------------------------- #

def test_compilar_no_ejecuta_el_python_del_usuario():
    """El mismo contrato que el test unitario, pero por el camino real:
    ``python V0/main.py juego.srcx`` no importa nada del proyecto."""
    files = _project(**{"extensions/calls/physics.py":
                        'from htims import hook\n'
                        "open('EJECUTADO', 'w').write('boom')\n"
                        '@hook("__x__", owner="T", returns="void")\n'
                        'def x(t): pass\n'})
    code, out, err = run_project(files, main="juego.srcx",
                                 args=["--emit-extensions"])
    assert code == 0, err
    payload = json.loads(out)
    root = payload["root"]
    assert not os.path.exists(os.path.join(root, "EJECUTADO")), (
        "compilar ejecutó el .py del proyecto")
    assert [h["name"] for h in payload["extensions"]["hooks"]] == ["__x__"]
