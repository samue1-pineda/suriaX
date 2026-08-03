"""e2e/visibility — reservas ``public``/``private``/``internal`` de punta a
punta, a través de la frontera REAL entre archivos (el linker de librerías).

Modelo de "paquete" del enforcement (``collect._same_package`` +
``loader._without_internal``): un paquete es una CARPETA. Estos tests lo
materializan con dos disposiciones:

  - **mismo paquete**: la ``.libsrx`` vive JUNTO al consumidor (mismo dir),
    así ``private`` es visible.
  - **otro paquete**: la ``.libsrx`` vive bajo ``./lib`` (otro dir), así
    ``private`` queda oculto y solo ``public`` cruza.

``internal`` nunca cruza — se filtra en el ORIGEN (el export ni lo lleva),
así que ni el mismo paquete lo ve.

Los casos POSITIVOS se ejecutan (``--run``) y comparan salida; los NEGATIVOS
corren solo el frontend y verifican el CÓDIGO del diagnóstico (contrato
estable), no el texto.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import assert_project_output, run_project  # noqa: E402

W = "fn __write__(str s) -> void;\n"

#: librería con las tres visibilidades sobre funciones y tipos.
LIB = (
    "public fn pub_fn() -> int { return 1; }\n"
    "private fn priv_fn() -> int { return 2; }\n"
    "internal fn int_fn() -> int { return 3; }\n"
    "public struct { int a; } Pub;\n"
    "private struct { int b; } Priv;\n"
    "#export as mylib\n"
)


def _same_pkg(imp: str, body: str) -> dict:
    """La lib JUNTO al consumidor (mismo dir = mismo paquete)."""
    return {
        "mylib.libsrx": LIB,
        "main.srcx": W + imp + "\nfn main() -> int {\n" + body + "\n    return 0;\n};\n",
    }


def _cross_pkg(imp: str, body: str) -> dict:
    """La lib bajo ./lib (otro dir = otro paquete)."""
    return {
        "lib/mylib.libsrx": LIB,
        "main.srcx": W + imp + "\nfn main() -> int {\n" + body + "\n    return 0;\n};\n",
    }


def _err(files: dict):
    code, out, err = run_project(files)  # solo frontend (sin --run)
    assert code != 0, f"se esperaba error de compilación; salió {code}. out={out!r}"
    return err


# --------------------------------------------------------------------------- #
# public: siempre visible
# --------------------------------------------------------------------------- #

def test_public_fn_visible_cross_package():
    assert_project_output(
        _cross_pkg("#import mylib", '    __write__(f"{mylib.pub_fn()}\\n");'), "1\n")


def test_public_struct_visible_cross_package():
    assert_project_output(
        _cross_pkg("#import mylib",
                   '    var mylib.Pub p = mylib.Pub{ a: 5 };\n'
                   '    __write__(f"{p.a}\\n");'),
        "5\n")


def test_lib_sin_anotaciones_es_publica():
    """Sin reservas, todo es público (compatibilidad con el corpus previo)."""
    files = {
        "lib/plain.libsrx": "fn f() -> int { return 9; }\n#export as plain\n",
        "main.srcx": W + "#import plain\n"
                         'fn main() -> int { __write__(f"{plain.f()}\\n"); return 0; };\n',
    }
    assert_project_output(files, "9\n")


# --------------------------------------------------------------------------- #
# private: visible dentro del mismo paquete, oculto fuera
# --------------------------------------------------------------------------- #

def test_private_visible_same_package():
    assert_project_output(
        _same_pkg("#import mylib", '    __write__(f"{mylib.priv_fn()}\\n");'), "2\n")


def test_private_visible_same_package_via_from():
    assert_project_output(
        _same_pkg("#from mylib #import priv_fn", '    __write__(f"{priv_fn()}\\n");'),
        "2\n")


def test_private_fn_oculto_cross_package():
    """Acceso por miembro: 'private' no está en los exports visibles -> SEM011."""
    assert "SEM011" in _err(_cross_pkg("#import mylib", "    return mylib.priv_fn();"))


def test_private_fn_oculto_cross_package_via_from():
    """'#from' con un 'private' de otro paquete -> diagnóstico específico SEM019."""
    assert "SEM019" in _err(
        _cross_pkg("#from mylib #import priv_fn", "    return priv_fn();"))


def test_private_struct_oculto_cross_package():
    """Un tipo 'private' tampoco cruza el límite del paquete."""
    err = _err(_cross_pkg("#import mylib",
                          "    var mylib.Priv p = mylib.Priv{ b: 1 };\n"
                          "    return p.b;"))
    assert ("SEM011" in err or "AST005" in err), err


# --------------------------------------------------------------------------- #
# internal: nunca cruza (ni siquiera dentro del mismo paquete)
# --------------------------------------------------------------------------- #

def test_internal_oculto_same_package():
    assert "SEM011" in _err(_same_pkg("#import mylib", "    return mylib.int_fn();"))


def test_internal_oculto_cross_package():
    assert "SEM011" in _err(_cross_pkg("#import mylib", "    return mylib.int_fn();"))


def test_internal_via_from_es_no_exporta_no_visibilidad():
    """'internal' se filtra en el origen: 'no exporta' (SEM011), no SEM019
    (nunca llega a evaluarse la regla de paquete)."""
    err = _err(_cross_pkg("#from mylib #import int_fn", "    return int_fn();"))
    assert "SEM011" in err and "SEM019" not in err, err


# --------------------------------------------------------------------------- #
# visibilidad de HOOKS: un 'private hook' despacha DENTRO de la librería pero
# no se conoce fuera (el que usa la librería no ve el hook, pero las funciones
# que lo usan siguen funcionando).
# --------------------------------------------------------------------------- #

def _box_pkg(hook_vis: str) -> dict:
    """Paquete 'enc' con un tipo B, su hook __print__ (visibilidad
    parametrizable) y una función pública 'show' que lo usa por dentro."""
    return {
        "lib/enc/main.libsrx": "#export package as enc\n",
        "lib/enc/box.libsrx": (
            "fn __write__(str s) -> void;\n"
            "public struct { str t; } B;\n"
            f"{hook_vis}hook fn __print__(B ptr b) -> void {{ __write__(b.t); }}\n"
            "public fn show(B ptr b) -> void { print(b); }\n"
            "public fn of(str s) -> B { return B{ t: s }; }\n"
            "#export as box\n"
        ),
    }


def test_private_hook_despacha_dentro_de_la_libreria():
    """'show' (público) usa el 'private hook' por dentro: sigue funcionando
    aunque el consumidor no conozca el hook."""
    files = {**_box_pkg("private "),
             "main.srcx": "fn __write__(str s) -> void;\n#import enc.box\n"
                          'fn main() -> int { var box.B x = box.of("hi\\n"); '
                          "box.show(&x); return 0; };\n"}
    assert_project_output(files, "hi\n")


def test_private_hook_no_se_exporta_al_consumidor():
    """Llamar 'print(&x)' DIRECTAMENTE en el consumidor no despacha: el hook
    'private' no cruzó el límite del paquete."""
    files = {**_box_pkg("private "),
             "main.srcx": "fn __write__(str s) -> void;\n#import enc.box\n"
                          'fn main() -> int { var box.B x = box.of("hi\\n"); '
                          "print(&x); return 0; };\n"}
    assert "SEM001" in _err(files), "el hook private no debe estar en el consumidor"


def test_public_hook_si_se_exporta_al_consumidor():
    """Con el hook 'public', el consumidor sí puede disparar 'print(&x)'."""
    files = {**_box_pkg("public "),
             "main.srcx": "fn __write__(str s) -> void;\n#import enc.box\n"
                          'fn main() -> int { var box.B x = box.of("bye\\n"); '
                          "print(&x); return 0; };\n"}
    assert_project_output(files, "bye\n")
