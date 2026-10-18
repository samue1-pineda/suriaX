"""bootstrap/semilla — la V2 versionada en ``src/semilla/`` está al día.

La SEMILLA es el compilador de suriaX compilado por sí mismo (la V2): con ella
y la VM se reconstruye el compilador SIN la V0 (``src/semilla/regenera.py``).
Dos promesas:

1. es la V1 de HOY: unidad por unidad, idéntica a lo que la V0 hace con
   ``src/`` (la etapa A del bootstrap). Si alguien cambia la V1 y no regenera
   la semilla, esta prueba lo dice;
2. se reproduce a sí misma: la semilla compila ``src/`` y da la semilla.

Con una VM de sanitizador la segunda se omite (la etapa tarda horas), como el
punto fijo.
"""

from __future__ import annotations

import glob
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)
sys.path.insert(0, os.path.dirname(_AQUI))

from helpers import omitir, vm_sanitizada  # noqa: E402
from test_bootstrap_v1 import _REPO, _STDLIB, _correr, _igual, _v1  # noqa: E402

_SEMILLA = os.path.join(_REPO, "src", "semilla")
_REGENERA = "python src/semilla/regenera.py"


def _unidades(carpeta: str) -> list:
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(carpeta, "*.phir")))


def test_la_semilla_es_la_v1_de_hoy():
    tmp, vm = _v1()                       # 'dumps/': la V0 compila la V1 de hoy
    semilla = _unidades(_SEMILLA)
    assert semilla, f"no hay semilla en {_SEMILLA}: {_REGENERA} --desde-v0"
    hoy = _unidades(os.path.join(tmp, "dumps"))
    assert semilla == hoy, (
        f"la semilla tiene otras unidades que la V1 de hoy: regenérala ({_REGENERA}).\n"
        f"  semilla: {semilla}\n  hoy: {hoy}")
    for unidad in semilla:
        try:
            _igual(unidad, os.path.join("dumps", unidad), os.path.join(_SEMILLA, unidad), vm, tmp)
        except AssertionError as e:
            raise AssertionError(f"la semilla no es la V1 de hoy: regenérala ({_REGENERA}).\n{e}") \
                from None


def test_la_semilla_se_reproduce_a_si_misma():
    tmp, vm = _v1()
    if vm_sanitizada(vm):
        omitir(f"'{vm}' es la VM de un sanitizador: compilar la V1 tarda horas")
    salida = os.path.join(tmp, "desde_la_semilla")
    os.makedirs(salida, exist_ok=True)
    hecho = _correr([vm, os.path.join(_SEMILLA, "main.srcx.phir"), "--run", "--quiet",
                     "--pasos", "0", "--", "main.srcx", os.path.join(salida, "main.srcx.phir"),
                     "--stdlib", _STDLIB], tmp, 600)
    assert hecho.returncode == 0, hecho.stderr[-2000:]
    assert _unidades(salida) == _unidades(_SEMILLA)
    for unidad in _unidades(_SEMILLA):
        _igual(unidad, os.path.join(_SEMILLA, unidad), os.path.join(salida, unidad), vm, tmp)
