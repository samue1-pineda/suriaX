"""backend/backend_cpp: la verificacion de propiedad y prestamos sobre el CFG.

Parte de ``test_backend_cpp.py`` (partido por tema); lo compartido esta en
``backend_cpp_support.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend_cpp_support import (  # noqa: E402
    _con_programa,
    _cpp,
)

# --------------------------------------------------------------------------- #
# la VERIFICACIÓN de propiedad y préstamos sobre el CFG (ROADMAP Fase 6)
# --------------------------------------------------------------------------- #
# El frontend rechaza lo que se ve mirando una sentencia; esto responde lo que
# solo se puede responder mirando CAMINOS. Que encuentre algo que el frontend
# dejó pasar es la prueba de que la etapa hacía falta — y que NO encuentre
# nada en un programa correcto es la prueba de que se puede creer.

def test_la_verificacion_calla_ante_un_programa_correcto():
    """Sin esto el verificador no valdría nada: uno que avisara siempre
    tendría razón siempre y no diría nada."""
    def comprobar(binario, phir, _corrida):
        salida = _cpp(binario, phir, "--mir").stdout
        assert "0 problema(s) de propiedad" in salida, salida
    _con_programa("""\
struct { int id; } R;
fn __write__(str s) -> void;
hook fn __free__(R ptr r) -> void { __write__("drop\\n"); };
fn toma(R r) -> int { return r.id; };
fn main() -> int { var R a = R{ id: 1 }; return toma(move a); };
""", comprobar)


def test_un_move_dentro_de_un_bucle_se_ve_en_el_grafo_y_no_en_el_arbol():
    """La segunda vuelta lee lo que la primera transfirió. El frontend acepta
    el programa —sobre el árbol el 'move' y la lectura están en ramas
    distintas—; sobre el CFG la arista de retorno del bucle une los dos
    caminos y la respuesta cambia. Es exactamente por esto que la
    verificación de propiedad vive en el MIR y no antes."""
    def comprobar(binario, phir, _corrida):
        salida = _cpp(binario, phir, "--mir").stdout
        assert "1 problema(s) de propiedad" in salida, salida
        assert "ALGUN camino lo transfiriera" in salida, salida
    _con_programa("""\
struct { int id; } R;
fn __write__(str s) -> void;
hook fn __free__(R ptr r) -> void { __write__("drop\\n"); };
fn toma(R r) -> int { return r.id; };
fn main() -> int {
    var R a = R{ id: 1 };
    var int i = 0;
    var int t = 0;
    while (i < 2) { t = t + toma(move a); i = i + 1; };
    return t;
};
""", comprobar)


def test_un_prestamo_no_sobrevive_al_valor_que_presta():
    """Los tiempos de vida de un 'ptr', que es la otra mitad de lo que la
    Fase 6 pide en esta etapa: prestar y después transferir deja el puntero
    apuntando a un valor que ya no es de nadie."""
    def comprobar(binario, phir, _corrida):
        salida = _cpp(binario, phir, "--mir").stdout
        assert "puntero sigue apuntando" in salida, salida
    _con_programa("""\
struct { int id; } R;
fn __write__(str s) -> void;
hook fn __free__(R ptr r) -> void { __write__("drop\\n"); };
fn toma(R r) -> int { return r.id; };
fn lee(R ptr p) -> int { return p.id; };
fn main() -> int {
    var R a = R{ id: 1 };
    var R ptr p = &a;
    var int n = toma(move a);
    return lee(p);
};
""", comprobar)
