"""Un hook DECLARADO POR EL PROYECTO, de punta a punta.

Es la prueba de que el HTIMS dejó de ser un descubridor y pasó a ampliar el
lenguaje: el mismo ``hook fn __gravity__`` compila y ejecuta en un proyecto
cuya extensión lo declara, y se rechaza en uno que no. Lo que se comprueba en
cada test:

  1. **el vocabulario es del proyecto**, no del compilador;
  2. la firma del ``.srcx`` se valida contra la que **prometió** la extensión;
  3. el hook **ejecuta** (el valor de retorno del programa lo demuestra);
  4. viaja al ``.phir`` con su nombre y su procedencia.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from helpers import run_project  # noqa: E402

_MANIFEST = ("project:   MiJuego\n"
             "logic_dir: extensions/logic\n"
             "calls_dir: extensions/calls\n")

# El cuerpo del hook se escribe en el .srcx (abajo), así que la firma es PURA:
# no declara 'cxx=True' ni 'logic'. Pedir C++ aquí sería EXT028.
_PHYSICS = ('from htims import signature\n'
            'PROJECT = "MiJuego"\n'
            '@signature("__gravity__", owner="Body",\n'
            '           params=["Body ptr mutable", "int"], returns="void")\n'
            'def gravity(body, dt):\n'
            '    """implementación de referencia"""\n')

#: 20 - 10*1 = 10, y 'main' devuelve ese valor: el exit code demuestra que el
#: hook corrió y que la mutación del receptor se propagó.
_PROGRAMA = """
struct { int vy; } Body;

hook fn __gravity__(Body ptr mutable b, int dt) -> void {
    b.vy = b.vy - 10 * dt;
}

fn main() -> int {
    var Body b = Body{ vy: 20 };
    b.__gravity__(1);
    return b.vy;
}
"""


def _proyecto(programa: str = _PROGRAMA, *, con_extension: bool = True) -> dict:
    files = {"juego.srcx": programa}
    if con_extension:
        files["extends.srcx"] = _MANIFEST
        files["extensions/logic/.keep"] = ""
        files["extensions/calls/physics.py"] = _PHYSICS
    return files


def _codigos(err: str) -> list[str]:
    import re
    return re.findall(r"\b(SEM\d+|EXT\d+)\b", err)


# --------------------------------------------------------------------------- #
# el camino feliz
# --------------------------------------------------------------------------- #

def test_un_hook_del_proyecto_compila_y_ejecuta():
    code, out, err = run_project(_proyecto(), main="juego.srcx", args=["--run"])
    assert code == 10, (
        f"el hook no ejecutó o no mutó el receptor (exit {code}).\n{out}\n{err}")


def test_sin_la_extension_el_mismo_programa_se_rechaza():
    """El vocabulario es del PROYECTO: sin quien lo declare, '__gravity__' no
    es un hook y el compilador lo dice."""
    code, out, err = run_project(_proyecto(con_extension=False),
                                 main="juego.srcx", args=["--run"])
    assert code != 0
    assert "SEM018" in err, err
    assert "__gravity__" in err


def test_el_error_de_hook_desconocido_lista_el_vocabulario_del_proyecto():
    """Con extensión, un hook que nadie declaró se rechaza — pero el mensaje
    incluye los que SÍ declara el proyecto, para no mandar al usuario al sitio
    equivocado."""
    programa = ("struct { int vy; } Body;\n"
                "hook fn __inventado__(Body ptr b) -> void { return; }\n"
                "fn main() -> int { return 0; }\n")
    code, out, err = run_project(_proyecto(programa), main="juego.srcx")
    assert "SEM018" in err
    assert "__gravity__" in err, (
        "el mensaje no menciona el vocabulario que aporta el proyecto")


# --------------------------------------------------------------------------- #
# la firma prometida se hace cumplir
# --------------------------------------------------------------------------- #

def _rechaza(cuerpo: str) -> str:
    programa = ("struct { int vy; } Body;\nstruct { int x; } Sound;\n"
                f"{cuerpo}\n"
                "fn main() -> int { return 0; }\n")
    code, out, err = run_project(_proyecto(programa), main="juego.srcx")
    assert code != 0, f"se esperaba rechazo y compiló:\n{out}"
    assert "SEM006" in err, err
    return err


def test_un_parametro_de_mas_se_rechaza():
    err = _rechaza("hook fn __gravity__(Body ptr mutable b, int dt, int x) "
                   "-> void { b.vy = 0; }")
    assert "2 parámetro" in err and "physics" in err


def test_un_tipo_de_parametro_distinto_se_rechaza():
    err = _rechaza("hook fn __gravity__(Body ptr mutable b, float dt) "
                   "-> void { b.vy = 0; }")
    assert "'float'" in err and "'int'" in err


def test_perder_el_mutable_se_rechaza():
    """El caso que un usuario comete de verdad: la extensión prometió poder
    escribir el receptor y la implementación lo declara de solo lectura."""
    err = _rechaza("hook fn __gravity__(Body ptr b, int dt) -> void { return; }")
    assert "Body ptr mutable" in err


def test_un_retorno_distinto_se_rechaza():
    err = _rechaza("hook fn __gravity__(Body ptr mutable b, int dt) -> int "
                   "{ return 1; }")
    assert "'void'" in err


def test_implementarlo_sobre_otro_tipo_se_rechaza():
    err = _rechaza("hook fn __gravity__(Sound ptr mutable s, int dt) -> void "
                   "{ s.x = 0; }")
    assert "Body" in err


# --------------------------------------------------------------------------- #
# lo que viaja en el artefacto
# --------------------------------------------------------------------------- #

def test_el_artefacto_se_emite_con_el_hook_del_proyecto():
    """El ``.phir`` se genera (el hook no bloquea la emisión) y el resumen del
    frontend lo cuenta como hook. Lo que VIAJA dentro —nombre y procedencia—
    lo fija ``test/unit/test_extension_vocabulary.py``, que puede mirar el
    ``Module`` sin depender de un directorio temporal."""
    code, out, err = run_project(_proyecto(), main="juego.srcx",
                                 args=["--emit-hir"])
    assert code == 0, err
    assert "1 hooks" in out, out
    assert "HIR (" in out, out
