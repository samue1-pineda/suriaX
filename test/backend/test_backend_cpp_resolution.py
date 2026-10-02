"""backend/backend_cpp: la resolucion del programa (llamadas, slots, destrucciones).

Parte de ``test_backend_cpp.py`` (partido por tema); lo compartido esta en
``backend_cpp_support.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend_cpp_support import (  # noqa: E402
    _con_referencia,
    _cpp,
)

# --------------------------------------------------------------------------- #
# RESOLUCIÓN: el lector no solo recorre el árbol, lo entiende
# --------------------------------------------------------------------------- #
# '--pretty' demuestra que el lector visita cada nodo; '--resolve' demuestra
# que sabe QUÉ significa: a qué función llama cada llamada, qué slots tiene
# cada marco y qué destruye cada bloque. Son preguntas distintas — imprimir
# 'foo(2, 3)' no exige saber a qué 'foo' se llama— y es la segunda la que un
# MIR necesita respondida antes de poder bajar nada.

def test_el_lector_resuelve_el_programa_de_referencia_entero():
    """Cero llamadas sin resolver: si el backend no sabe a qué llama un sitio,
    no puede generar código para él y tiene que verse."""
    def comprobar(binario, phir, _tmp):
        resultado = _cpp(binario, phir, "--resolve")
        assert resultado.returncode == 0, (
            f"quedaron llamadas sin resolver:\n{resultado.stdout}"
            f"\n{resultado.stderr}")
        assert "0 llamada(s) sin resolver" in resultado.stdout
    _con_referencia(comprobar)


def test_cada_funcion_de_la_imagen_aparece_con_sus_slots():
    """Los slots (parámetros y locales en un solo espacio de índices) son lo
    primero que un MIR asigna; numerarlos aquí evita que cada backend invente
    su propia numeración."""
    def comprobar(binario, phir, _tmp):
        salida = _cpp(binario, phir, "--resolve").stdout
        assert "fn main" in salida
        assert "entrada: main" in salida
        # los prototipos del host se distinguen de las funciones con cuerpo
        assert "(prototipo: lo aporta el host)" in salida
        assert "slot 0  param" in salida
    _con_referencia(comprobar)


def test_las_destrucciones_del_bloque_llegan_ligadas_a_su_hook():
    """El frontend decidió DÓNDE muere cada valor; el backend comprueba que el
    destructor que nombra existe de verdad en la imagen."""
    def comprobar(binario, phir, _tmp):
        salida = _cpp(binario, phir, "--resolve").stdout
        assert "destruye " in salida, salida
        assert "NO LIGADO" not in salida, (
            "un drop nombra un hook que la imagen no tiene:\n" + salida)
    _con_referencia(comprobar)


def test_un_hook_de_un_primitivo_se_marca_nativo_y_no_como_agujero():
    """'len(s)' sobre un 'str' viaja como HookRef, pero ninguna unidad puede
    declararlo (SEM006 prohíbe colgarle hooks a un primitivo): lo implementa
    el backend. Confundirlo con 'no sé a qué llama esto' sería un falso
    agujero."""
    def comprobar(binario, phir, _tmp):
        salida = _cpp(binario, phir, "--resolve").stdout
        assert "-> nativo" in salida, salida
    _con_referencia(comprobar)
